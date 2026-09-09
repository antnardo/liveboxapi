"""The upstream link, the LAN, and the devices on it.

The LAN address range is the one setting in this package that can lock you out
of your own network: change the DHCP range and every device renews into a
subnet the box no longer serves. :meth:`NetworkApi.set_lan_config` therefore
reads the current configuration and only replaces the fields it was asked to
change, rather than sending a full payload built from defaults.
"""

from typing import Any

from liveboxapi.models import Device, GponStatus, WanStatus
from liveboxapi.session import LiveboxSession

__all__ = ["NetworkApi"]

_LAN_BRIDGE = "NetMaster.LAN.default.Bridge.lan"
"""Where the LAN really lives. ``NMC:setLANIP`` exists too, and nobody uses it."""


class NetworkApi:
    """WAN status, optical diagnostics, LAN configuration and device list."""

    def __init__(self, session: LiveboxSession, wan_interface: str = "veip0") -> None:
        self._session = session
        # Fibre boxes carry the WAN on veip0; DSL and Ethernet models differ,
        # which is why this is a constructor argument rather than a constant.
        self._wan_interface = wan_interface

    # ---------------------------------------------------------------------- WAN

    def wan_status(self) -> WanStatus:
        return WanStatus.from_api(self._session.call("NMC", "getWANStatus"))

    def public_ip(self) -> str:
        return self.wan_status().ipv4

    def gpon(self) -> GponStatus:
        """Optical power, temperature and negotiated rate of the fibre module.

        Falling receive power is the early sign of a splice or connector going
        bad, well before the link drops: worth graphing rather than polling only
        when something breaks.
        """
        mibs = self._session.call(f"NeMo.Intf.{self._wan_interface}", "getMIBs", {"mibs": "gpon"})
        return GponStatus.from_api((mibs.get("gpon") or {}).get(self._wan_interface, {}))

    def wan_counters(self) -> tuple[int, int]:
        """Cumulative ``(received, sent)`` byte counters of the WAN interface.

        Throughput is the difference between two readings: the box exposes no
        rate of its own, and its own counters have a history of wrapping.
        """
        stats = self._session.call(f"NeMo.Intf.{self._wan_interface}", "getNetDevStats")
        return int(stats.get("RxBytes", 0)), int(stats.get("TxBytes", 0))

    def ipv6(self) -> dict[str, Any]:
        return self._session.call("NMC.IPv6", "get")

    def iptv_status(self) -> str:
        return str(self._session.call("NMC.OrangeTV", "getIPTVStatus").get("IPTVStatus", ""))

    # ---------------------------------------------------------------------- LAN

    def lan_config(self) -> dict[str, Any]:
        """Address, prefix length, DHCP range and lease time of the LAN bridge."""
        return self._session.call(_LAN_BRIDGE, "getIPv4")

    def set_lan_config(self, **changes: Any) -> None:
        """Change LAN settings, leaving untouched everything not named.

        Accepts any field of :meth:`lan_config` — ``DHCPMinAddress``,
        ``DHCPMaxAddress``, ``LeaseTime``, ``Address``, ``PrefixLength``,
        ``DHCPEnable``… The current configuration is read first and merged, so
        a caller changing the lease time cannot accidentally reset the subnet.
        """
        if not changes:
            return
        current = dict(self.lan_config())
        current.update(changes)
        self._session.call(_LAN_BRIDGE, "setIPv4", current)

    # ------------------------------------------------------------------ devices

    def devices(self, active_only: bool = True) -> list[Device]:
        """Devices known to the box, optionally only those connected now.

        Entries without a hardware address — the internal telephony endpoints —
        are dropped: they are not network devices and only confuse inventories.
        """
        expression = "physical and .Active==true" if active_only else "physical"
        found = self._session.call("Devices", "get", {"expression": expression}) or []
        return [Device.from_api(d) for d in found if d.get("PhysAddress")]

    def device(self, mac: str) -> Device | None:
        """One device by hardware address, or ``None``."""
        target = mac.upper()
        return next((d for d in self.devices(active_only=False) if d.mac == target), None)

    def unknown_devices(self, known_macs: list[str]) -> list[Device]:
        """Active devices whose address is not in ``known_macs``.

        Randomised addresses are excluded: phones rotate them by design, so
        flagging them produces noise that trains people to ignore the report.
        """
        known = {m.upper() for m in known_macs}
        return [d for d in self.devices() if d.mac not in known and not d.has_private_mac]
