"""Network: optical readings, the merge-before-write on the LAN, device filtering."""

import pytest

from liveboxapi.network import NetworkApi


@pytest.fixture
def network(session):
    return NetworkApi(session)


class TestWan:
    def test_status_is_typed(self, network, http):
        http.enqueue(
            {
                "data": {
                    "LinkState": "up",
                    "WanState": "up",
                    "IPAddress": "203.0.113.42",
                    "GponState": "O5_Operation",
                }
            }
        )
        status = network.wan_status()
        assert status.up and status.fibre_operational

    def test_optical_readings_are_converted(self, network, http):
        http.enqueue({"status": {"gpon": {"veip0": {"SignalRxPower": -18530, "Temperature": 58}}}})
        gpon = network.gpon()
        assert gpon.rx_dbm == -18.53
        assert gpon.temperature_c == 58

    def test_the_wan_interface_is_configurable(self, session, http):
        """Fibre uses veip0; other links do not, hence a constructor argument."""
        http.enqueue({"status": {"gpon": {}}})
        NetworkApi(session, wan_interface="eth0").gpon()
        assert http.calls[-1][0] == "NeMo.Intf.eth0"

    def test_counters_come_back_as_a_pair(self, network, http):
        http.enqueue({"status": {"RxBytes": 100, "TxBytes": 50}})
        assert network.wan_counters() == (100, 50)


class TestLan:
    def test_writing_keeps_the_fields_it_was_not_given(self, network, http):
        """A lease-time change must not reset the subnet: read, merge, write."""
        http.enqueue(
            {
                "data": {
                    "Address": "192.168.1.1",
                    "PrefixLength": 24,
                    "DHCPEnable": True,
                    "DHCPMinAddress": "192.168.1.100",
                    "DHCPMaxAddress": "192.168.1.199",
                    "LeaseTime": 86400,
                }
            }
        )
        http.enqueue({"status": True})
        network.set_lan_config(LeaseTime=43200)
        sent = http.last_parameters()
        assert sent["LeaseTime"] == 43200
        assert sent["Address"] == "192.168.1.1"
        assert sent["DHCPMinAddress"] == "192.168.1.100"

    def test_nothing_to_change_sends_nothing(self, network, http):
        before = len(http.posts)
        network.set_lan_config()
        assert len(http.posts) == before


class TestDevices:
    def test_entries_without_an_address_are_dropped(self, network, http):
        """The internal telephony endpoints are not network devices."""
        http.enqueue(
            {
                "status": [
                    {"PhysAddress": "00:00:5E:00:53:01", "Name": "a server"},
                    {"Name": "DECT"},
                ]
            }
        )
        assert len(network.devices()) == 1

    def test_active_only_is_the_default(self, network, http):
        http.enqueue({"status": []})
        network.devices()
        assert http.last_parameters()["expression"] == "physical and .Active==true"

    def test_unknown_devices_ignore_randomised_addresses(self, network, http):
        """Phones rotate their address by design; flagging them trains people to ignore reports."""
        http.enqueue(
            {
                "status": [
                    {"PhysAddress": "3E:00:00:00:00:02", "Name": "a phone"},
                    {"PhysAddress": "00:00:5E:00:53:02", "Name": "an intruder"},
                    {"PhysAddress": "00:00:5E:00:53:01", "Name": "known"},
                ]
            }
        )
        found = network.unknown_devices(known_macs=["00:00:5e:00:53:01"])
        assert [d.name for d in found] == ["an intruder"]
