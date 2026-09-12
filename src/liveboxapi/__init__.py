"""A Python client for Orange Livebox routers.

The box speaks JSON-RPC over HTTP — the "sah" protocol of SoftAtHome — and
exposes far more than its web interface shows: DHCP reservations, firewall
rules, IPv6 pinholes, per-device internet blocking, optical diagnostics, the
call log, even its own configuration backup.

    from liveboxapi import Livebox

    with Livebox(password="…") as box:
        print(box.network.wan_status().ipv4)
        for lease in box.dhcp.static_leases():
            print(lease.ip, lease.mac)

Reading is safe; writing reconfigures a live home network. Open the session
read-only when a program has no business changing anything:

    with Livebox(password="…", readonly=True) as box:
        ...                       # any set*/add*/delete* now raises

What sets this client apart from reading a blog post about your model:
:meth:`Livebox.functions` asks the box itself what it can do, with full
signatures. Firmware differs between models — the Wi-Fi 7 variant names its
radio interfaces differently from the Livebox 7 — so the device in front of you
is the only reliable documentation.
"""

from liveboxapi.credentials import Credentials, resolve_credentials
from liveboxapi.dhcp import DhcpApi
from liveboxapi.errors import (
    AuthenticationError,
    LiveboxError,
    MalformedResponseError,
    ReadOnlyError,
)
from liveboxapi.firewall import FirewallApi
from liveboxapi.models import (
    BoxIdentity,
    Device,
    DmzEntry,
    FunctionSignature,
    GponStatus,
    Lease,
    MissedCall,
    PortForward,
    ScheduleEntry,
    StaticLease,
    UserAccount,
    WanStatus,
    WifiInterface,
)
from liveboxapi.network import NetworkApi
from liveboxapi.schedule import ScheduleApi
from liveboxapi.session import BatchCall, LiveboxSession
from liveboxapi.system import SystemApi, identify
from liveboxapi.transport import BodyDecoder
from liveboxapi.voice import VoiceApi
from liveboxapi.wifi import WifiApi

__version__ = "0.1.1"

__all__ = [
    "AuthenticationError",
    "BatchCall",
    "BodyDecoder",
    "BoxIdentity",
    "Credentials",
    "Device",
    "DhcpApi",
    "DmzEntry",
    "FirewallApi",
    "FunctionSignature",
    "GponStatus",
    "Lease",
    "Livebox",
    "LiveboxError",
    "LiveboxSession",
    "MalformedResponseError",
    "MissedCall",
    "NetworkApi",
    "PortForward",
    "ReadOnlyError",
    "ScheduleApi",
    "ScheduleEntry",
    "StaticLease",
    "SystemApi",
    "UserAccount",
    "VoiceApi",
    "WanStatus",
    "WifiApi",
    "WifiInterface",
    "__version__",
    "identify",
    "resolve_credentials",
]


class Livebox:
    """A box, with its features grouped by area.

    ``box.dhcp``, ``box.firewall``, ``box.network``, ``box.wifi``,
    ``box.schedule``, ``box.voice`` and ``box.system`` each hold one area. The
    raw plumbing stays reachable through :meth:`call`, :meth:`batch` and
    :meth:`introspect` for anything this package does not wrap yet.
    """

    def __init__(
        self,
        url: str | None = None,
        user: str | None = None,
        password: str | None = None,
        *,
        readonly: bool = False,
        credentials: Credentials | None = None,
        timeout: float | tuple[float, float] = (5.0, 15.0),
        wan_interface: str = "veip0",
        session: LiveboxSession | None = None,
        verify: bool | str = True,
    ) -> None:
        # An existing session can be passed in to share one login between
        # several facades, or to hand the tests a recorded transport.
        self.session = session or LiveboxSession(
            credentials or resolve_credentials(url, user, password),
            readonly=readonly,
            timeout=timeout,
            verify=verify,
        )
        self.system = SystemApi(self.session)
        self.network = NetworkApi(self.session, wan_interface=wan_interface)
        self.dhcp = DhcpApi(self.session)
        self.firewall = FirewallApi(self.session)
        self.wifi = WifiApi(self.session)
        self.schedule = ScheduleApi(self.session)
        self.voice = VoiceApi(self.session)

    # Plumbing, delegated so that callers never reach for ``box.session``.

    def call(self, service: str, method: str, parameters: dict | None = None):
        """One call, raising on refusal."""
        return self.session.call(service, method, parameters)

    def raw(self, service: str, method: str, parameters: dict | None = None) -> dict:
        """One call, returning the whole response including any error."""
        return self.session.raw(service, method, parameters)

    def batch(self, calls) -> dict:
        """Many calls in one session — the difference between seconds and minutes."""
        return self.session.batch(calls)

    def introspect(self, path: str, depth: int = 1) -> dict:
        """An object's own description of itself."""
        return self.session.introspect(path, depth)

    def functions(self, path: str, *, writes_only: bool = False):
        """The methods an object exposes, read from the box."""
        return self.session.functions(path, writes_only=writes_only)

    def parameters(self, path: str) -> dict:
        """An object's parameters and their values."""
        return self.session.parameters(path)

    def health(self) -> dict:
        """A one-call-per-area summary, for dashboards and alerting."""
        wan = self.network.wan_status()
        gpon = self.network.gpon()
        return {
            "wan_up": wan.up,
            "public_ip": wan.ipv4,
            "ipv6_prefix": wan.ipv6_prefix,
            "gpon_state": wan.gpon_state,
            "fibre_rx_dbm": gpon.rx_dbm,
            "fibre_tx_dbm": gpon.tx_dbm,
            "fibre_temperature_c": gpon.temperature_c,
            "uptime_days": round(self.system.uptime().total_seconds() / 86400, 1),
            "firmware": self.system.firmware_version(),
            "iptv": self.network.iptv_status(),
            "voip": self.voice.line_status(),
            "missed_calls": self.voice.unviewed_count(),
        }

    def __enter__(self) -> "Livebox":
        self.session.login()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.session.logout()

    def __repr__(self) -> str:
        return f"<Livebox {self.session.credentials.url}>"
