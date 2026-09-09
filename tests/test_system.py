"""System: identity, accounts, and the operator-side backup."""

from datetime import timedelta

import pytest

from liveboxapi.system import SystemApi


@pytest.fixture
def system(session):
    return SystemApi(session)


class TestIdentity:
    def test_firmware_string_is_returned_whole(self, system, http):
        """Its prefix identifies the hardware line, so it must not be trimmed."""
        http.enqueue({"status": {"SoftwareVersion": "SGW7-fr-G03.R09.C02_02"}})
        assert system.firmware_version() == "SGW7-fr-G03.R09.C02_02"

    def test_uptime_is_a_timedelta(self, system, http):
        http.enqueue({"status": {"UpTime": 86400}})
        assert system.uptime() == timedelta(days=1)

    def test_a_missing_uptime_is_zero(self, system, http):
        http.enqueue({"status": {}})
        assert system.uptime() == timedelta(0)


class TestAccounts:
    def test_accounts_are_typed(self, system, http):
        http.enqueue({"status": [{"name": "admin", "enable": True, "groups": ["http", "admin"]}]})
        accounts = system.users()
        assert accounts[0].is_admin

    def test_changing_a_password_sends_both_fields(self, system, http):
        http.enqueue({"status": True})
        system.change_password("admin", "new-secret")
        assert http.last_parameters() == {"name": "admin", "password": "new-secret"}

    def test_the_checked_variant_sends_the_old_one(self, system, http):
        http.enqueue({"status": True})
        system.change_password_checked("admin", "new", "old")
        assert http.last_parameters()["old_password"] == "old"


class TestBackup:
    def test_status_is_returned_raw(self, system, http):
        http.enqueue({"status": {"Enable": True, "ConfigDate": "2026-09-09T10:41:28Z"}})
        assert system.backup_status()["Enable"] is True

    def test_age_is_computed_against_local_time(self, system, http):
        """The date ends in Z but is local: comparing to UTC gives a negative age."""
        http.enqueue({"status": {"ConfigDate": "2000-01-01T00:00:00Z"}})
        age = system.backup_age()
        assert age is not None and age.days > 9000

    def test_an_unreadable_date_is_none(self, system, http):
        http.enqueue({"status": {"ConfigDate": "never"}})
        assert system.backup_age() is None

    def test_a_missing_date_is_none(self, system, http):
        http.enqueue({"status": {}})
        assert system.backup_age() is None

    def test_a_backup_can_be_triggered(self, system, http):
        http.enqueue({"status": True})
        system.launch_backup()
        assert http.calls[-1] == ("NMC.NetworkConfig", "launchNetworkBackup")

    def test_a_restore_can_be_triggered(self, system, http):
        http.enqueue({"status": True})
        system.launch_restore()
        assert http.calls[-1] == ("NMC.NetworkConfig", "launchNetworkRestore")
