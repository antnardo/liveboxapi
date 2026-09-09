"""Typed views over the box's answers.

The API returns deeply nested dictionaries whose keys change spelling from one
service to the next: ``IPAddress`` here, ``ipaddress`` there, ``Address``
elsewhere. Every model below is built by a ``from_api`` classmethod that absorbs
those inconsistencies once, so that callers never index a raw payload.

Models are frozen: they are snapshots of a state read at one instant, not
handles on the device. Mutating one would suggest the box changed.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

__all__ = [
    "Device",
    "DmzEntry",
    "FunctionSignature",
    "GponStatus",
    "Lease",
    "MissedCall",
    "PortForward",
    "ScheduleEntry",
    "StaticLease",
    "UserAccount",
    "WanStatus",
    "WifiInterface",
]


def _as_bool(value: object) -> bool:
    """The box mixes real booleans, ``"true"`` and ``"Enabled"`` for the same idea."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "enabled", "on", "up", "1"}
    return bool(value)


def _parse_time(value: str) -> datetime | None:
    """Timestamps come as ISO 8601, sometimes with a ``Z`` the box does not honour."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Device:
    """A device the box has seen, whether or not it is connected right now."""

    mac: str
    name: str
    ipv4: str
    ipv6: tuple[str, ...]
    active: bool
    device_type: str
    interface: str

    @classmethod
    def from_api(cls, payload: dict) -> "Device":
        addresses = [a.get("Address", "") for a in payload.get("IPv4Address") or [] if a.get("Address")]
        v6 = [
            a.get("Address", "")
            for a in payload.get("IPv6Address") or []
            if a.get("Address") and not a["Address"].lower().startswith("fe80")
        ]
        return cls(
            mac=(payload.get("PhysAddress") or "").upper(),
            name=payload.get("Name") or payload.get("Alias") or "",
            ipv4=addresses[0] if addresses else "",
            ipv6=tuple(v6),
            active=_as_bool(payload.get("Active")),
            device_type=payload.get("DeviceType") or "",
            interface=payload.get("InterfaceName") or payload.get("Layer2Interface") or "",
        )

    @property
    def has_private_mac(self) -> bool:
        """Whether the address is randomised, as phones and tablets do by default.

        The second hexadecimal digit carries the "locally administered" bit. A
        DHCP reservation on such an address breaks the day the device rotates
        it, and the stale reservation then lingers forever — which is why this
        deserves a property rather than a comment in someone's script.
        """
        if len(self.mac) < 2:
            return False
        try:
            return int(self.mac[1], 16) & 0x2 == 0x2
        except ValueError:
            return False


@dataclass(frozen=True, slots=True)
class StaticLease:
    """A DHCP reservation."""

    mac: str
    ip: str

    @property
    def sort_key(self) -> tuple[int, ...]:
        return tuple(int(part) for part in self.ip.split(".") if part.isdigit())


@dataclass(frozen=True, slots=True)
class Lease:
    """A lease currently held, reserved or not."""

    mac: str
    ip: str
    reserved: bool
    active: bool
    friendly_name: str = ""
    remaining_seconds: int = -1

    @classmethod
    def from_api(cls, payload: dict) -> "Lease":
        return cls(
            mac=(payload.get("MACAddress") or "").upper(),
            ip=payload.get("IPAddress") or "",
            reserved=_as_bool(payload.get("Reserved")),
            active=_as_bool(payload.get("Active")),
            friendly_name=payload.get("FriendlyName") or "",
            remaining_seconds=int(payload.get("LeaseTimeRemaining", -1)),
        )


@dataclass(frozen=True, slots=True)
class PortForward:
    """An inbound port redirection."""

    id: str
    origin: str
    description: str
    protocol: str
    external_port: str
    internal_port: str
    destination: str
    enabled: bool
    source_prefix: str = ""

    @classmethod
    def from_api(cls, payload: dict) -> "PortForward":
        return cls(
            id=payload.get("Id") or "",
            origin=payload.get("Origin") or "",
            description=payload.get("Description") or "",
            protocol=str(payload.get("Protocol") or ""),
            external_port=str(payload.get("ExternalPort") or ""),
            internal_port=str(payload.get("InternalPort") or ""),
            destination=payload.get("DestinationIPAddress") or "",
            enabled=_as_bool(payload.get("Enable")),
            source_prefix=payload.get("SourcePrefix") or "",
        )

    @property
    def protocol_names(self) -> tuple[str, ...]:
        """``"6/17"`` means TCP and UDP: the box speaks IANA numbers, humans do not."""
        names = {"1": "ICMP", "6": "TCP", "17": "UDP", "58": "ICMPv6"}
        return tuple(names.get(p, p) for p in self.protocol.split("/") if p)


@dataclass(frozen=True, slots=True)
class DmzEntry:
    """A host exposed wholesale. Included for completeness; you should have none."""

    id: str
    destination: str
    enabled: bool
    source_prefix: str = ""

    @classmethod
    def from_api(cls, payload: dict) -> "DmzEntry":
        return cls(
            id=payload.get("Id") or "",
            destination=payload.get("DestinationIPAddress") or "",
            enabled=_as_bool(payload.get("Enable")),
            source_prefix=payload.get("SourcePrefix") or "",
        )


@dataclass(frozen=True, slots=True)
class WanStatus:
    """The upstream link."""

    up: bool
    link_type: str
    protocol: str
    ipv4: str
    ipv6: str
    ipv6_prefix: str
    gpon_state: str
    last_error: str

    @classmethod
    def from_api(cls, payload: dict) -> "WanStatus":
        return cls(
            up=payload.get("LinkState") == "up" and payload.get("WanState") == "up",
            link_type=payload.get("LinkType") or "",
            protocol=payload.get("Protocol") or "",
            ipv4=payload.get("IPAddress") or "",
            ipv6=payload.get("IPv6Address") or "",
            ipv6_prefix=payload.get("IPv6DelegatedPrefix") or "",
            gpon_state=payload.get("GponState") or "",
            last_error=payload.get("LastConnectionError") or "",
        )

    @property
    def fibre_operational(self) -> bool:
        """``O5_Operation`` is the one healthy state of the optical unit's state machine."""
        return self.gpon_state.startswith("O5")


@dataclass(frozen=True, slots=True)
class GponStatus:
    """Optical diagnostics, the early warning of a failing fibre."""

    rx_dbm: float | None
    tx_dbm: float | None
    temperature_c: float | None
    max_mbps: int | None

    @classmethod
    def from_api(cls, payload: dict) -> "GponStatus":
        # Powers come in thousandths of a dBm, which no one expects.
        rx = payload.get("SignalRxPower")
        tx = payload.get("SignalTxPower")
        return cls(
            rx_dbm=round(rx / 1000, 2) if isinstance(rx, int | float) else None,
            tx_dbm=round(tx / 1000, 2) if isinstance(tx, int | float) else None,
            temperature_c=payload.get("Temperature"),
            max_mbps=payload.get("MaxBitRateSupported"),
        )


@dataclass(frozen=True, slots=True)
class WifiInterface:
    """One radio interface — one band of one network name."""

    name: str
    ssid: str
    enabled: bool
    status: str
    security_mode: str
    wps_enabled: bool
    advertised: bool
    band: str = ""

    @classmethod
    def from_api(cls, name: str, payload: dict) -> "WifiInterface":
        security = payload.get("Security") or {}
        wps = payload.get("WPS") or {}
        return cls(
            name=name,
            ssid=payload.get("SSID") or "",
            enabled=_as_bool(payload.get("Enable")),
            status=payload.get("VAPStatus") or "",
            security_mode=security.get("ModeEnabled") or "",
            wps_enabled=_as_bool(wps.get("Enable")),
            advertised=_as_bool(payload.get("SSIDAdvertisementEnabled")),
            band="2.4GHz" if "2g" in name else "5GHz" if "5g" in name else "6GHz" if "6g" in name else "",
        )

    @property
    def uses_wpa3(self) -> bool:
        return "WPA3" in self.security_mode.upper()


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """A parental-control schedule, the mechanism behind per-device internet blocking."""

    mac: str
    enabled: bool
    override: str
    value: str

    @classmethod
    def from_api(cls, payload: dict) -> "ScheduleEntry":
        return cls(
            mac=(payload.get("ID") or "").upper(),
            enabled=_as_bool(payload.get("enable")),
            override=payload.get("override") or "",
            value=payload.get("value") or "",
        )

    @property
    def blocked(self) -> bool:
        """``Disable`` here means "this device may not reach the internet"."""
        return self.value == "Disable"


@dataclass(frozen=True, slots=True)
class MissedCall:
    """One missed call from the box's own call log."""

    number: str
    start_time: datetime | None
    viewed: bool

    @classmethod
    def from_api(cls, payload: dict) -> "MissedCall":
        return cls(
            number=payload.get("remoteNumber") or "",
            start_time=_parse_time(payload.get("startTime") or ""),
            viewed=_as_bool(payload.get("viewed")),
        )


@dataclass(frozen=True, slots=True)
class UserAccount:
    """An administration account of the box itself."""

    name: str
    enabled: bool
    groups: tuple[str, ...]

    @classmethod
    def from_api(cls, payload: dict) -> "UserAccount":
        return cls(
            name=payload.get("name") or "",
            enabled=_as_bool(payload.get("enable")),
            groups=tuple(payload.get("groups") or ()),
        )

    @property
    def is_admin(self) -> bool:
        return "admin" in self.groups


@dataclass(frozen=True, slots=True)
class FunctionSignature:
    """One method of one datamodel object, as the box describes itself.

    This is what makes the difference between guessing an API from a blog post
    written for another model and reading it off the device in front of you.
    """

    name: str
    return_type: str
    arguments: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @classmethod
    def from_api(cls, payload: dict) -> "FunctionSignature":
        return cls(
            name=payload.get("name") or "",
            return_type=payload.get("type") or "",
            arguments=tuple(
                (a.get("type") or "", a.get("name") or "") for a in payload.get("arguments") or []
            ),
        )

    @property
    def writes(self) -> bool:
        """A useful first filter when exploring: does this method change anything?"""
        prefixes = ("set", "add", "del", "remove", "create", "update", "enable", "disable", "commit")
        return self.name.startswith(prefixes)

    def __str__(self) -> str:
        args = ", ".join(f"{t} {n}" for t, n in self.arguments)
        return f"{self.name}({args})"
