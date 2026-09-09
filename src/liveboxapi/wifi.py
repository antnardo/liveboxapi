"""Radios, network names and their security.

Interface naming is the one place where models genuinely diverge. A Livebox 6 or
7 numbers them — ``vap2g0priv0`` — while the Wi-Fi 7 variant does not:
``vap2g0priv``. Rather than hard-code either, :meth:`WifiApi.interfaces`
discovers the names that answer on the box in front of it.

Security is written through ``NeMo.Intf.lan``, not through the interface itself,
and the payload carries the network name and its passphrase alongside the
security mode. That makes an automated change riskier than it looks: a partial
payload can rewrite a network's identity. The method exists, with the warning
attached.
"""

from typing import Any

from liveboxapi.errors import LiveboxError
from liveboxapi.models import WifiInterface
from liveboxapi.session import LiveboxSession

__all__ = ["CANDIDATE_INTERFACES", "WifiApi"]

CANDIDATE_INTERFACES = (
    "vap2g0priv",
    "vap5g0priv",
    "vap6g0priv",
    "vap2g0priv0",
    "vap5g0priv0",
    "vap6g0priv0",
    "vap2g0guest",
    "vap5g0guest",
    "vap2g0guest0",
    "vap5g0guest0",
)
"""Names seen across Livebox 5 to W7, used only as a fallback (see below)."""

BRIDGES = ("lan", "guest")
"""Where interfaces are asked for wholesale: the home bridge, then the guest one."""

_WLAN_WRITE_INTERFACE = "NeMo.Intf.lan"


class WifiApi:
    """Radio state, network names, WPS and the guest network."""

    def __init__(self, session: LiveboxSession) -> None:
        self._session = session
        self._cache: dict[str, Any] | None = None

    # -------------------------------------------------------------------- state

    def status(self) -> dict[str, Any]:
        """Global Wi-Fi state: radios on or off, WPS, scheduling."""
        return self._session.call("NMC.Wifi", "get")

    def enabled(self) -> bool:
        return bool(self.status().get("Enable"))

    def set_enabled(self, enabled: bool) -> None:
        """Turn every radio on or off.

        Both fields are sent: ``Enable`` is the wish, ``Status`` the state, and
        firmware that reads only one leaves the radios in an odd half-state
        otherwise.
        """
        self._session.call("NMC.Wifi", "set", {"Enable": enabled, "Status": enabled})

    def wps_enabled(self) -> bool:
        return bool(self.status().get("WPSEnable"))

    def set_wps(self, enabled: bool) -> None:
        """Turn WPS off — worth doing even with the radios down.

        The setting survives a radio restart, so a box whose Wi-Fi is switched
        back on by a support call or a front-panel button comes back with
        whatever was configured, not with what you assumed.
        """
        self._session.call("NMC.Wifi", "setWPSEnable", {"enable": enabled})

    # ------------------------------------------------------------------- guest

    def guest_enabled(self) -> bool:
        return bool(self._session.call("NMC.Guest", "get").get("Enable"))

    def set_guest(self, enabled: bool) -> None:
        self._session.call("NMC.Guest", "set", {"Enable": enabled})

    # -------------------------------------------------------------- interfaces

    def _read_vaps(self) -> dict[str, Any]:
        """Every Wi-Fi interface, in as few calls as possible.

        Asking a bridge for its ``wlanvap`` returns all the interfaces beneath
        it at once, so two calls cover the home and guest networks. Probing the
        known names one by one costs ten calls and several seconds, and is kept
        only as a fallback for firmware where the bridges answer nothing.
        """
        if self._cache is not None:
            return self._cache
        found: dict[str, Any] = {}
        for bridge in BRIDGES:
            try:
                mibs = self._session.call(f"NeMo.Intf.{bridge}", "getMIBs", {"mibs": "wlanvap"})
            except LiveboxError:
                continue
            found.update(mibs.get("wlanvap") or {})
        if not found:
            for name in CANDIDATE_INTERFACES:
                try:
                    mibs = self._session.call(f"NeMo.Intf.{name}", "getMIBs", {"mibs": "wlanvap"})
                except LiveboxError:
                    continue
                found.update(mibs.get("wlanvap") or {})
        self._cache = found
        return found

    def interface_names(self) -> tuple[str, ...]:
        """The interface names this box actually uses."""
        return tuple(self._read_vaps())

    def interfaces(self) -> list[WifiInterface]:
        """Every radio interface with its security mode and WPS state."""
        return [WifiInterface.from_api(name, payload) for name, payload in self._read_vaps().items()]

    def refresh(self) -> None:
        """Forget the discovered interfaces, after switching the radios on."""
        self._cache = None

    def radios(self) -> dict[str, Any]:
        """Channel, bandwidth and standards of each radio."""
        radios: dict[str, Any] = {}
        for bridge in BRIDGES:
            try:
                mibs = self._session.call(f"NeMo.Intf.{bridge}", "getMIBs", {"mibs": "wlanradio"})
            except LiveboxError:
                continue
            radios.update(mibs.get("wlanradio") or {})
        return radios

    def set_security(self, interface: str, mode: str, passphrase: str | None = None) -> None:
        """Change the security mode of one interface.

        ``mode`` takes the datamodel's own spelling, ``WPA2-Personal``,
        ``WPA2-WPA3-Personal``, ``WPA3-Personal``… Read the accepted values off
        the box with ``session.introspect`` rather than guessing them.

        Two warnings. The write goes to the LAN object rather than to the
        interface, which is surprising but correct. And the structure it expects
        also carries the network name and its key, so a malformed payload can
        rename a network or drop its passphrase — pass ``passphrase`` whenever
        the box may treat the field as authoritative. Prefer the web interface
        unless you are rebuilding a box from scratch.
        """
        security: dict[str, Any] = {"ModeEnabled": mode}
        if passphrase is not None:
            security["KeyPassPhrase"] = passphrase
        self._session.call(
            _WLAN_WRITE_INTERFACE,
            "setWLANConfig",
            {"mibs": {"wlanvap": {interface: {"Security": security}}}},
        )
