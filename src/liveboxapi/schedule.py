"""Cutting a device off the internet, by hardware address.

There is no "block this device" call. What exists is parental control: a weekly
schedule per device, with an override. An empty schedule plus an override set to
``Disable`` is a permanent block, and that is how every tool does it.

Worth knowing before relying on it: the block applies to traffic leaving towards
the internet, **not** to the local network. A blocked camera can still be
reached from a laptop on the same LAN, and can still reach that laptop. It stops
the device phoning home; it does not isolate it.
"""

from liveboxapi.errors import LiveboxError
from liveboxapi.models import ScheduleEntry
from liveboxapi.session import LiveboxSession

__all__ = ["SCHEDULE_TYPE", "ScheduleApi"]

SCHEDULE_TYPE = "ToD"
"""Time-of-day schedules, the type parental control uses."""


class ScheduleApi:
    """Per-device internet blocking."""

    def __init__(self, session: LiveboxSession) -> None:
        self._session = session

    def entries(self) -> list[ScheduleEntry]:
        """Every schedule the box holds, blocking or not.

        Leftovers accumulate here: a device blocked once for an evening keeps an
        inert entry forever. Auditing this list is how you find a parental
        control someone set years ago and forgot.
        """
        answer = self._session.raw("Scheduler", "getSchedules", {"type": SCHEDULE_TYPE})
        info = (answer.get("data") or {}).get("scheduleInfo") or []
        return [ScheduleEntry.from_api(entry) for entry in info]

    def entry(self, mac: str) -> ScheduleEntry | None:
        target = mac.upper()
        return next((e for e in self.entries() if e.mac == target), None)

    def is_blocked(self, mac: str) -> bool:
        entry = self.entry(mac)
        return entry is not None and entry.blocked

    def block(self, mac: str) -> None:
        """Cut a device off the internet, creating its schedule if needed.

        No schedule at all means "never blocked", so the first block has to
        create one; afterwards only the override changes.
        """
        if self._has_schedule(mac):
            self._override(mac, "Disable")
            return
        self._session.call(
            "Scheduler",
            "addSchedule",
            {
                "type": SCHEDULE_TYPE,
                "info": {
                    "ID": mac.upper(),
                    "base": "Weekly",
                    "def": "Enable",
                    "schedule": [],
                    "enable": True,
                    "override": "Disable",
                },
            },
        )

    def unblock(self, mac: str) -> None:
        """Give a device its internet access back."""
        if self._has_schedule(mac):
            self._override(mac, "Enable")

    def remove(self, mac: str) -> None:
        """Delete the schedule entirely, which also unblocks the device."""
        self._session.call("Scheduler", "removeSchedules", {"type": SCHEDULE_TYPE, "ID": mac.upper()})

    def blocked_devices(self) -> list[str]:
        """Addresses currently cut off."""
        return [entry.mac for entry in self.entries() if entry.blocked]

    def _has_schedule(self, mac: str) -> bool:
        try:
            answer = self._session.raw("Scheduler", "getSchedule", {"type": SCHEDULE_TYPE, "ID": mac.upper()})
        except LiveboxError:
            return False
        return bool(answer.get("status"))

    def _override(self, mac: str, override: str) -> None:
        self._session.call(
            "Scheduler",
            "overrideSchedule",
            {"type": SCHEDULE_TYPE, "ID": mac.upper(), "override": override},
        )
