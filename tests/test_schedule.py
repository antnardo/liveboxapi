"""Blocking a device: create the schedule the first time, override it afterwards."""

import pytest

from liveboxapi.schedule import ScheduleApi

CAMERA = "00:00:5E:00:53:03"


@pytest.fixture
def schedule(session):
    return ScheduleApi(session)


class TestReading:
    def test_entries_are_read_from_the_nested_answer(self, schedule, http):
        http.enqueue(
            {
                "status": True,
                "data": {
                    "scheduleInfo": [
                        {"ID": CAMERA, "enable": True, "override": "Disable", "value": "Disable"}
                    ]
                },
            }
        )
        entries = schedule.entries()
        assert entries[0].mac == CAMERA
        assert entries[0].blocked

    def test_no_schedule_at_all_is_not_an_error(self, schedule, http):
        http.enqueue({"status": False})
        assert schedule.entries() == []

    def test_blocked_devices_lists_only_the_blocked(self, schedule, http):
        http.enqueue(
            {
                "status": True,
                "data": {
                    "scheduleInfo": [
                        {"ID": CAMERA, "value": "Disable"},
                        {"ID": "AA:BB:CC:DD:EE:FF", "value": "Enable"},
                    ]
                },
            }
        )
        assert schedule.blocked_devices() == [CAMERA]


class TestBlocking:
    def test_the_first_block_creates_a_schedule(self, schedule, http):
        """No schedule means "never blocked", so there is nothing to override yet."""
        http.enqueue({"status": False})  # getSchedule: none
        http.enqueue({"status": True})  # addSchedule
        schedule.block(CAMERA)
        assert http.calls[-1] == ("Scheduler", "addSchedule")
        sent = http.last_parameters()["info"]
        assert sent["override"] == "Disable"
        assert sent["schedule"] == []

    def test_a_later_block_only_overrides(self, schedule, http):
        http.enqueue({"status": True, "data": {"scheduleInfo": {"value": "Enable"}}})
        http.enqueue({"status": True})
        schedule.block(CAMERA)
        assert http.calls[-1] == ("Scheduler", "overrideSchedule")
        assert http.last_parameters()["override"] == "Disable"

    def test_unblocking_an_unknown_device_does_nothing(self, schedule, http):
        http.enqueue({"status": False})
        schedule.unblock(CAMERA)
        assert http.calls[-1] == ("Scheduler", "getSchedule")

    def test_unblocking_sets_the_override_back(self, schedule, http):
        http.enqueue({"status": True, "data": {"scheduleInfo": {"value": "Disable"}}})
        http.enqueue({"status": True})
        schedule.unblock(CAMERA)
        assert http.last_parameters()["override"] == "Enable"

    def test_removing_deletes_the_schedule(self, schedule, http):
        http.enqueue({"status": True})
        schedule.remove(CAMERA)
        assert http.calls[-1] == ("Scheduler", "removeSchedules")

    def test_addresses_are_upper_cased(self, schedule, http):
        http.enqueue({"status": True})
        schedule.remove("00:00:5e:00:53:03")
        assert http.last_parameters()["ID"] == CAMERA
