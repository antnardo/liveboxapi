"""DHCP: the lying address field, the uppercase rule, and idempotent reservations."""

import pytest

from liveboxapi.dhcp import DhcpApi
from liveboxapi.errors import LiveboxError


@pytest.fixture
def dhcp(session):
    return DhcpApi(session)


class TestStaticLeases:
    def test_the_address_comes_from_the_lease_path(self, dhcp, http):
        """``MACAddress`` repeats the same wrong value; the path holds the truth."""
        http.enqueue(
            {
                "status": [
                    {
                        "MACAddress": "00:00:00:00:00:00",
                        "IPAddress": "192.168.1.10",
                        "LeasePath": "DHCPv4.Server.Pool.default.Rule.default.Lease.01:00:00:5e:00:53:01",
                    }
                ]
            }
        )
        assert dhcp.static_leases()[0].mac == "00:00:5E:00:53:01"

    def test_it_falls_back_to_the_field_when_there_is_no_path(self, dhcp, http):
        http.enqueue({"status": [{"MACAddress": "aa:bb:cc:dd:ee:ff", "IPAddress": "192.168.1.5"}]})
        assert dhcp.static_leases()[0].mac == "AA:BB:CC:DD:EE:FF"

    def test_results_are_sorted_by_address(self, dhcp, http):
        http.enqueue(
            {
                "status": [
                    {"IPAddress": "192.168.1.100", "LeasePath": "…Lease.01:aa:aa:aa:aa:aa:aa"},
                    {"IPAddress": "192.168.1.9", "LeasePath": "…Lease.01:bb:bb:bb:bb:bb:bb"},
                ]
            }
        )
        assert [lease.ip for lease in dhcp.static_leases()] == ["192.168.1.9", "192.168.1.100"]

    def test_no_reservation_is_not_an_error(self, dhcp, http):
        http.enqueue({"status": None})
        assert dhcp.static_leases() == []


class TestWrites:
    def test_the_address_is_upper_cased(self, dhcp, http):
        """Lowercase makes the box answer success and do nothing."""
        http.enqueue({"status": True})
        dhcp.add_static_lease("00:00:5e:00:53:01", "192.168.1.10")
        assert http.last_parameters()["MACAddress"] == "00:00:5E:00:53:01"

    def test_an_existing_reservation_is_not_an_error(self, dhcp, http):
        http.enqueue({"errors": [{"error": 393221, "description": "IP address already reserved"}]})
        dhcp.add_static_lease("AA:BB:CC:DD:EE:FF", "192.168.1.5")  # must not raise

    def test_it_can_be_made_strict(self, dhcp, http):
        http.enqueue({"errors": [{"error": 393221, "description": "already"}]})
        with pytest.raises(LiveboxError):
            dhcp.add_static_lease("AA:BB:CC:DD:EE:FF", "192.168.1.5", ignore_existing=False)

    def test_another_error_still_raises(self, dhcp, http):
        http.enqueue({"errors": [{"error": 13, "description": "permission denied"}]})
        with pytest.raises(LiveboxError):
            dhcp.add_static_lease("AA:BB:CC:DD:EE:FF", "192.168.1.5")

    def test_deletion_upper_cases_too(self, dhcp, http):
        http.enqueue({"status": True})
        dhcp.delete_static_lease("aa:bb:cc:dd:ee:ff")
        assert http.last_parameters() == {"MACAddress": "AA:BB:CC:DD:EE:FF"}


class TestLeases:
    def test_the_extra_nesting_level_is_flattened(self, dhcp, http):
        """Leases hide under a rule name, one level deeper than everything else."""
        http.enqueue(
            {
                "status": {
                    "default": {
                        "01:aa": {"IPAddress": "192.168.1.10", "MACAddress": "aa", "Reserved": True},
                        "01:bb": {"IPAddress": "192.168.1.150", "MACAddress": "bb", "Reserved": False},
                    }
                }
            }
        )
        assert len(dhcp.leases()) == 2

    def test_dynamic_leases_are_the_undeclared_ones(self, dhcp, http):
        http.enqueue(
            {
                "status": {
                    "default": {
                        "01:aa": {"IPAddress": "192.168.1.10", "Reserved": True},
                        "01:bb": {"IPAddress": "192.168.1.150", "Reserved": False},
                    }
                }
            }
        )
        assert [lease.ip for lease in dhcp.dynamic_leases()] == ["192.168.1.150"]


class TestPool:
    def test_lease_time_is_sent_as_seconds(self, dhcp, http):
        http.enqueue({"status": True})
        dhcp.set_lease_time(86400)
        assert http.last_parameters() == {"leasetime": 86400}

    def test_the_guest_pool_is_a_different_service(self, session, http):
        http.enqueue({"status": []})
        DhcpApi(session, pool="guest").static_leases()
        assert http.calls[-1][0] == "DHCPv4.Server.Pool.guest"
