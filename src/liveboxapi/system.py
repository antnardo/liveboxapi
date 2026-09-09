"""The box itself: identity, clock, accounts, and its own configuration backup.

The backup deserves a word. Orange keeps a copy of the box configuration on its
own servers, and the box can be told to push a fresh one or to restore it. That
is the real safety net the day the hardware is swapped, and it is worth
triggering before any risky change — even though its content cannot be read
back, which is why this package can start it but not inspect it.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from liveboxapi.models import UserAccount
from liveboxapi.session import LiveboxSession

__all__ = ["SystemApi"]


class SystemApi:
    """Identity, time, accounts and configuration backup."""

    def __init__(self, session: LiveboxSession) -> None:
        self._session = session

    # ----------------------------------------------------------------- identity

    def device_info(self) -> dict[str, Any]:
        """Everything the box says about itself: model, firmware, serial, uptime."""
        return self._session.call("DeviceInfo", "get")

    def firmware_version(self) -> str:
        """For example ``SGW7-fr-G03.R09.C02_02``.

        The prefix identifies the hardware line, and it matters: ``SG70`` is a
        Livebox 7, ``SGW7`` the Wi-Fi 7 variant, and their Wi-Fi interfaces are
        named differently. Read this before applying a recipe found elsewhere.
        """
        return str(self.device_info().get("SoftwareVersion", ""))

    def model_name(self) -> str:
        return str(self.device_info().get("ProductClass", ""))

    def serial_number(self) -> str:
        return str(self.device_info().get("SerialNumber", ""))

    def uptime(self) -> timedelta:
        return timedelta(seconds=int(self.device_info().get("UpTime", 0)))

    def reboot_count(self) -> int:
        return int(self.device_info().get("NumberOfReboots", 0))

    def connection_info(self) -> dict[str, Any]:
        """Offer name, WAN mode and provisioning state."""
        return self._session.call("NMC", "get")

    # --------------------------------------------------------------------- time

    def time(self) -> str:
        """The box clock, as it formats it — an RFC 1123 string, not ISO 8601."""
        return str(self._session.call("Time", "getTime").get("time", ""))

    def ntp_servers(self) -> list[str]:
        servers = self._session.call("Time", "getNTPServers").get("servers", {})
        return [value for value in servers.values() if value]

    # ----------------------------------------------------------------- accounts

    def users(self) -> list[UserAccount]:
        """Administration accounts. A stock box has exactly one."""
        return [UserAccount.from_api(u) for u in self._session.call("UserManagement", "getUsers") or []]

    def change_password(self, name: str, password: str) -> None:
        """Set an account password.

        The first thing to do on a replacement box, before anything else can
        talk to it: the factory password is the first eight characters of the
        Wi-Fi key, printed on the label and therefore known to anyone who has
        seen the back of the router.
        """
        self._session.call("UserManagement", "changePassword", {"name": name, "password": password})

    def change_password_checked(self, name: str, password: str, old_password: str) -> None:
        """Same, but the box verifies the previous password first."""
        self._session.call(
            "UserManagement",
            "changePasswordSec",
            {"name": name, "password": password, "old_password": old_password},
        )

    def add_user(self, name: str, password: str, groups: list[str] | None = None) -> None:
        """Create an account. Rarely useful: one admin account is the sane setup."""
        self._session.call(
            "UserManagement",
            "addUser",
            {"name": name, "password": password, "groups": groups or ["http"], "enable": True},
        )

    def remove_user(self, name: str) -> None:
        self._session.call("UserManagement", "removeUser", {"name": name})

    # ------------------------------------------------------------------- backup

    def backup_status(self) -> dict[str, Any]:
        """Whether the operator-side backup is on, and when it last ran."""
        return self._session.call("NMC.NetworkConfig", "get")

    def backup_age(self) -> timedelta | None:
        """How old the last backup is, or ``None`` if the date is unreadable.

        The date carries a ``Z`` suffix but is local time on at least some
        firmware — comparing it to UTC gives a negative age. It is therefore
        compared to local time here, which is right in every case that matters:
        an alert on "older than a week".
        """
        raw = str(self.backup_status().get("ConfigDate", ""))
        if not raw:
            return None
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", ""))
        except ValueError:
            return None
        return datetime.now(UTC).replace(tzinfo=None) - stamp

    def launch_backup(self, delay: bool = False) -> None:
        """Push a fresh configuration backup to the operator."""
        self._session.call("NMC.NetworkConfig", "launchNetworkBackup", {"delay": delay})

    def launch_restore(self) -> None:
        """Restore the operator-side backup. Reconfigures the box wholesale."""
        self._session.call("NMC.NetworkConfig", "launchNetworkRestore", {})

    def set_backup_enabled(self, enabled: bool) -> None:
        self._session.call("NMC.NetworkConfig", "enableNetworkBR", {"state": enabled})
