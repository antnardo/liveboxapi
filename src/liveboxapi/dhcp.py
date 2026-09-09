"""DHCP reservations and current leases.

Two firmware quirks are handled here so that callers never meet them.

**The reservation list lies about addresses.** ``getStaticLeases`` returns a
``MACAddress`` field that repeats the same value across entries. The real
address is inside ``LeasePath``, after ``Lease.01:``. Anything that trusts the
obvious field builds a wrong inventory — quietly.

**Writes want uppercase.** ``addStaticLease`` with a lowercase address returns
success and does nothing at all. Every address is upper-cased on the way out.
"""

import re
from typing import Any

from liveboxapi.errors import ERROR_ALREADY_RESERVED, LiveboxError
from liveboxapi.models import Lease, StaticLease
from liveboxapi.session import LiveboxSession

__all__ = ["DEFAULT_POOL", "DhcpApi"]

DEFAULT_POOL = "default"
"""The LAN pool. ``guest`` is the second one, served on its own bridge."""

_LEASE_PATH_MAC = re.compile(r"Lease\.01:([0-9a-fA-F:]+)$")


class DhcpApi:
    """Static reservations, live leases and pool settings."""

    def __init__(self, session: LiveboxSession, pool: str = DEFAULT_POOL) -> None:
        self._session = session
        self._pool = pool

    @property
    def _service(self) -> str:
        return f"DHCPv4.Server.Pool.{self._pool}"

    # ------------------------------------------------------------ reservations

    def static_leases(self) -> list[StaticLease]:
        """Every reservation, sorted by address, with the real hardware address."""
        entries = self._session.call(self._service, "getStaticLeases") or []
        leases = [StaticLease(mac=self._real_mac(entry), ip=entry.get("IPAddress", "")) for entry in entries]
        return sorted(leases, key=lambda lease: lease.sort_key)

    @staticmethod
    def _real_mac(entry: dict[str, Any]) -> str:
        match = _LEASE_PATH_MAC.search(entry.get("LeasePath", ""))
        return (match.group(1) if match else entry.get("MACAddress", "")).upper()

    def add_static_lease(self, mac: str, ip: str, *, ignore_existing: bool = True) -> None:
        """Reserve an address.

        An identical reservation makes the box answer with an error code that
        means "already there". That is a success for anyone writing idempotent
        configuration, so it is swallowed unless asked otherwise.
        """
        try:
            self._session.call(self._service, "addStaticLease", {"MACAddress": mac.upper(), "IPAddress": ip})
        except LiveboxError as exc:
            if not (ignore_existing and exc.code == ERROR_ALREADY_RESERVED):
                raise

    def set_static_lease(self, mac: str, ip: str, enable: bool = True) -> None:
        """Change an existing reservation in place."""
        self._session.call(
            self._service,
            "setStaticLease",
            {"MACAddress": mac.upper(), "IPAddress": ip, "Enable": enable},
        )

    def delete_static_lease(self, mac: str) -> None:
        self._session.call(self._service, "deleteStaticLease", {"MACAddress": mac.upper()})

    def reserve_current_address(self, mac: str) -> None:
        """Turn the address a device currently holds into a reservation."""
        self._session.call(self._service, "addLeaseFromPool", {"MACAddress": mac.upper()})

    # ------------------------------------------------------------------ leases

    def leases(self) -> list[Lease]:
        """Every lease in the pool, reserved or dynamic.

        The response nests leases under a rule name, one level deeper than the
        rest of this API, which is flattened here.
        """
        by_rule = self._session.call(self._service, "getLeases") or {}
        return [
            Lease.from_api(entry)
            for rule in by_rule.values()
            if isinstance(rule, dict)
            for entry in rule.values()
        ]

    def dynamic_leases(self) -> list[Lease]:
        """Leases held without a reservation — the devices you did not declare."""
        return [lease for lease in self.leases() if not lease.reserved]

    # ------------------------------------------------------------------- pool

    def pool_config(self) -> dict[str, Any]:
        """Range, lease time, distributed DNS, domain name, ARP protection."""
        return self._session.call(self._service, "get")

    def pools(self) -> dict[str, Any]:
        """Every pool the box serves, including ``guest``."""
        return self._session.call("DHCPv4.Server", "getDHCPServerPool") or {}

    def set_lease_time(self, seconds: int) -> None:
        """Change the lease duration without touching the address range."""
        self._session.call(self._service, "setLeaseTime", {"leasetime": seconds})
