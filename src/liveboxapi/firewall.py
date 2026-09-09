"""Inbound rules: port forwarding, IPv6 pinholes, DMZ, levels, UPnP, remote admin.

Three things are worth knowing before writing here.

**Commit is selective.** Port forwardings and pinholes only take effect after
``Firewall:commit``; levels, DMZ and ping do not need it. The methods below
commit on their own by default, so a forgotten commit cannot leave a rule that
exists in the configuration and not in the packet filter.

**Protocols are numbers.** ``"6"`` is TCP, ``"17"`` is UDP, and both together
are ``"6/17"``. Names are rejected, silently in some firmware.

**Rule identifiers carry their origin.** A rule created through the web
interface is stored as ``webui_<name>``, and deletion wants that full form plus
the origin as a separate argument.
"""

from typing import Any

from liveboxapi.models import DmzEntry, PortForward
from liveboxapi.session import LiveboxSession

__all__ = ["PROTOCOL_TCP", "PROTOCOL_TCP_UDP", "PROTOCOL_UDP", "FirewallApi"]

PROTOCOL_TCP = "6"
PROTOCOL_UDP = "17"
PROTOCOL_TCP_UDP = "6/17"

_DEFAULT_ORIGIN = "webui"
"""Origin used by the web interface. Rules created with it show up there too."""


class FirewallApi:
    """Everything that decides what may enter the network."""

    def __init__(self, session: LiveboxSession) -> None:
        self._session = session

    # -------------------------------------------------------------- port rules

    def port_forwardings(self, origin: str | None = None) -> dict[str, PortForward]:
        """Redirections, keyed by identifier.

        Pass ``origin="upnp"`` to list what devices opened by themselves — an
        empty result there is worth asserting in any monitoring job, since it is
        the only visible trace of a device punching a hole on its own.
        """
        parameters = {"origin": origin} if origin else {}
        rules = self._session.call("Firewall", "getPortForwarding", parameters) or {}
        return {key: PortForward.from_api(value) for key, value in rules.items()}

    def set_port_forwarding(
        self,
        rule_id: str,
        destination: str,
        internal_port: str,
        external_port: str = "",
        protocol: str = PROTOCOL_TCP,
        *,
        description: str = "",
        origin: str = _DEFAULT_ORIGIN,
        source_interface: str = "data",
        source_prefix: str = "",
        enable: bool = True,
        persistent: bool = True,
        commit: bool = True,
    ) -> str:
        """Create or replace a redirection, and commit it.

        ``external_port`` defaults to ``internal_port``, the common case.
        """
        payload: dict[str, Any] = {
            "id": rule_id,
            "origin": origin,
            "sourceInterface": source_interface,
            "internalPort": str(internal_port),
            "externalPort": str(external_port or internal_port),
            "destinationIPAddress": destination,
            "sourcePrefix": source_prefix,
            "protocol": protocol,
            "enable": enable,
            "persistent": persistent,
            "description": description or rule_id,
            "destinationMACAddress": "",
        }
        created = self._session.call("Firewall", "setPortForwarding", payload)
        if commit:
            self.commit()
        return str(created or rule_id)

    def delete_port_forwarding(
        self,
        rule_id: str,
        origin: str = _DEFAULT_ORIGIN,
        destination: str = "",
        *,
        commit: bool = True,
    ) -> None:
        self._session.call(
            "Firewall",
            "deletePortForwarding",
            {"id": rule_id, "origin": origin, "destinationIPAddress": destination},
        )
        if commit:
            self.commit()

    def enable_port_forwarding(
        self, rule_id: str, enable: bool, origin: str = _DEFAULT_ORIGIN, *, commit: bool = True
    ) -> None:
        """Turn a rule off without losing it."""
        self._session.call(
            "Firewall", "enablePortForwarding", {"id": rule_id, "origin": origin, "enable": enable}
        )
        if commit:
            self.commit()

    # ---------------------------------------------------------------- pinholes

    def pinholes(self) -> dict[str, Any]:
        """IPv6 inbound rules.

        There is no address translation in IPv6: a pinhole names the internal
        address directly, so it exposes exactly one host and port pair.
        """
        return self._session.call("Firewall", "getPinhole") or {}

    def set_pinhole(
        self,
        rule_id: str,
        destination: str,
        destination_port: str,
        protocol: str = PROTOCOL_TCP,
        *,
        description: str = "",
        origin: str = _DEFAULT_ORIGIN,
        source_interface: str = "data",
        source_port: str = "",
        source_prefix: str = "",
        enable: bool = True,
        persistent: bool = True,
        commit: bool = True,
    ) -> str:
        """Open an IPv6 pinhole, and commit it."""
        payload = {
            "id": rule_id,
            "origin": origin,
            "sourceInterface": source_interface,
            "sourcePort": source_port,
            "destinationPort": str(destination_port),
            "destinationIPAddress": destination,
            "sourcePrefix": source_prefix,
            "protocol": protocol,
            "ipversion": 6,
            "enable": enable,
            "persistent": persistent,
            "description": description or rule_id,
            "destinationMACAddress": "",
        }
        created = self._session.call("Firewall", "setPinhole", payload)
        if commit:
            self.commit()
        return str(created or rule_id)

    def delete_pinhole(self, rule_id: str, origin: str = _DEFAULT_ORIGIN, *, commit: bool = True) -> None:
        self._session.call("Firewall", "deletePinhole", {"id": rule_id, "origin": origin})
        if commit:
            self.commit()

    def commit(self) -> None:
        """Apply pending port and pinhole changes to the running filter."""
        self._session.call("Firewall", "commit")

    # --------------------------------------------------------------------- DMZ

    def dmz(self) -> dict[str, DmzEntry]:
        return {
            key: DmzEntry.from_api(value)
            for key, value in (self._session.call("Firewall", "getDMZ") or {}).items()
        }

    def set_dmz(
        self,
        rule_id: str,
        destination: str,
        *,
        source_interface: str = "data",
        source_prefix: str = "",
        enable: bool = True,
    ) -> None:
        """Expose a host entirely. Needs no commit — and needs a good reason."""
        self._session.call(
            "Firewall",
            "setDMZ",
            {
                "id": rule_id,
                "sourceInterface": source_interface,
                "destinationIPAddress": destination,
                "sourcePrefix": source_prefix,
                "enable": enable,
            },
        )

    def delete_dmz(self, rule_id: str) -> None:
        self._session.call("Firewall", "deleteDMZ", {"id": rule_id})

    # ------------------------------------------------------ protocol forwarding

    def protocol_forwardings(self) -> dict[str, Any]:
        """Whole-protocol forwarding, used by some VPN passthrough setups."""
        return self._session.call("Firewall", "getProtocolForwarding") or {}

    def delete_protocol_forwarding(self, rule_id: str) -> None:
        self._session.call("Firewall", "deleteProtocolForwarding", {"id": rule_id})

    # ------------------------------------------------------------------ levels

    def level(self) -> str:
        """``High``, ``Medium``, ``Low`` or ``Custom``.

        The level governs outbound filtering; inbound traffic is blocked at
        every level except through the rules above.
        """
        return str(self._session.call("Firewall", "getFirewallLevel"))

    def set_level(self, level: str) -> None:
        self._session.call("Firewall", "setFirewallLevel", {"level": level})

    def ipv6_level(self) -> str:
        return str(self._session.call("Firewall", "getFirewallIPv6Level"))

    def set_ipv6_level(self, level: str) -> None:
        self._session.call("Firewall", "setFirewallIPv6Level", {"level": level})

    def custom_rules(self, chain: str = "Custom") -> dict[str, Any]:
        """Rules of a custom chain. Inert unless the level is ``Custom``."""
        return self._session.call("Firewall", "getCustomRule", {"chain": chain}) or {}

    # -------------------------------------------------------------------- ping

    def respond_to_ping(self, source_interface: str = "data") -> dict[str, bool]:
        """Whether the box answers ICMP echo from the internet, per family."""
        return self._session.call("Firewall", "getRespondToPing", {"sourceInterface": source_interface})

    def set_respond_to_ping(self, ipv4: bool, ipv6: bool, source_interface: str = "data") -> None:
        self._session.call(
            "Firewall",
            "setRespondToPing",
            {
                "sourceInterface": source_interface,
                "service_enable": {"enableIPv4": ipv4, "enableIPv6": ipv6},
            },
        )

    # -------------------------------------------------------------------- UPnP

    def upnp_enabled(self) -> bool:
        """Whether devices may open inbound ports by themselves."""
        return bool(self._session.call("UPnP-IGD", "get").get("Enable"))

    def set_upnp(self, enabled: bool) -> None:
        """Turn the UPnP gateway on or off.

        The argument is nested twice because the declared parameter is itself
        called ``parameters`` — a quirk of this bus, not a typo here.
        """
        self._session.call("UPnP-IGD", "set", {"parameters": {"Enable": enabled}})

    # ----------------------------------------------------------- remote access

    def remote_access(self) -> dict[str, Any]:
        """Whether the administration interface is reachable from the internet."""
        return self._session.call("RemoteAccess", "get")

    def enable_remote_access(
        self, port: int = 0, secure: bool = True, timeout: int = 0, source_prefix: str = ""
    ) -> int:
        """Open remote administration, returning the port the box chose.

        ``timeout`` in seconds is the safer way to use this: the box closes the
        door on its own afterwards.
        """
        return int(
            self._session.call(
                "RemoteAccess",
                "enable",
                {"port": port, "secure": secure, "timeout": timeout, "sourcePrefix": source_prefix},
            )
            or 0
        )

    def disable_remote_access(self) -> None:
        self._session.call("RemoteAccess", "disable")
