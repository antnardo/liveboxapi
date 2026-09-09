"""Models: the normalisation of everything the box spells inconsistently."""

import pytest

from liveboxapi.models import (
    Device,
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


class TestDevice:
    def test_address_and_name_are_normalised(self):
        device = Device.from_api(
            {
                "PhysAddress": "00:00:5e:00:53:01",
                "Name": "raspberrypi",
                "IPv4Address": [{"Address": "192.168.1.10"}],
                "Active": True,
                "DeviceType": "Computer",
            }
        )
        assert device.mac == "00:00:5E:00:53:01"
        assert device.ipv4 == "192.168.1.10"

    def test_link_local_addresses_are_dropped(self):
        device = Device.from_api(
            {
                "PhysAddress": "aa:bb:cc:dd:ee:ff",
                "IPv6Address": [{"Address": "fe80::1"}, {"Address": "2001:db8::1"}],
            }
        )
        assert device.ipv6 == ("2001:db8::1",)

    def test_alias_is_used_when_there_is_no_name(self):
        assert Device.from_api({"PhysAddress": "a", "Alias": "printer"}).name == "printer"

    @pytest.mark.parametrize("mac", ["3E:00:00:00:00:02", "AE:00:00:00:00:01", "AA:00:00:00:00:00"])
    def test_randomised_addresses_are_recognised(self, mac):
        assert Device.from_api({"PhysAddress": mac}).has_private_mac

    @pytest.mark.parametrize("mac", ["00:00:5E:00:53:01", "00:00:5E:00:53:02", "00:00:5E:00:53:04"])
    def test_hardware_addresses_are_not_flagged(self, mac):
        assert not Device.from_api({"PhysAddress": mac}).has_private_mac

    def test_an_empty_address_does_not_crash(self):
        assert not Device.from_api({"PhysAddress": ""}).has_private_mac


class TestBooleans:
    @pytest.mark.parametrize("value", [True, "true", "Enabled", "up", "1"])
    def test_every_spelling_of_yes(self, value):
        assert Lease.from_api({"Active": value}).active

    @pytest.mark.parametrize("value", [False, "false", "Disabled", "", None])
    def test_every_spelling_of_no(self, value):
        assert not Lease.from_api({"Active": value}).active


class TestStaticLease:
    def test_sorting_is_numeric_not_lexicographic(self):
        leases = [StaticLease("A", "192.168.1.100"), StaticLease("B", "192.168.1.9")]
        assert [lease.ip for lease in sorted(leases, key=lambda x: x.sort_key)] == [
            "192.168.1.9",
            "192.168.1.100",
        ]


class TestPortForward:
    def test_protocol_numbers_become_names(self):
        rule = PortForward.from_api({"Protocol": "6/17"})
        assert rule.protocol_names == ("TCP", "UDP")

    def test_an_unknown_protocol_is_left_alone(self):
        assert PortForward.from_api({"Protocol": "47"}).protocol_names == ("47",)

    def test_ports_are_strings_even_when_sent_as_numbers(self):
        assert PortForward.from_api({"ExternalPort": 443}).external_port == "443"


class TestWanStatus:
    def test_up_needs_both_states(self):
        assert WanStatus.from_api({"LinkState": "up", "WanState": "up"}).up
        assert not WanStatus.from_api({"LinkState": "up", "WanState": "down"}).up

    def test_o5_is_the_healthy_optical_state(self):
        assert WanStatus.from_api({"GponState": "O5_Operation"}).fibre_operational
        assert not WanStatus.from_api({"GponState": "O2_3_Standby"}).fibre_operational


class TestGponStatus:
    def test_powers_are_thousandths_of_a_dbm(self):
        status = GponStatus.from_api({"SignalRxPower": -18530, "SignalTxPower": 2140})
        assert (status.rx_dbm, status.tx_dbm) == (-18.53, 2.14)

    def test_missing_readings_stay_none(self):
        assert GponStatus.from_api({}).rx_dbm is None


class TestWifiInterface:
    @pytest.mark.parametrize(
        "name,band", [("vap2g0priv", "2.4GHz"), ("vap5g0priv0", "5GHz"), ("vap6g0priv", "6GHz")]
    )
    def test_band_is_read_from_the_name(self, name, band):
        assert WifiInterface.from_api(name, {}).band == band

    def test_wpa3_detection_covers_the_mixed_mode(self):
        mixed = WifiInterface.from_api(
            "vap2g0priv", {"Security": {"ModeEnabled": "WPA3-Personal-Compatibility"}}
        )
        legacy = WifiInterface.from_api("vap2g0priv", {"Security": {"ModeEnabled": "WPA2-Personal"}})
        assert mixed.uses_wpa3 and not legacy.uses_wpa3


class TestScheduleEntry:
    def test_disable_means_blocked(self):
        assert ScheduleEntry.from_api({"ID": "aa:bb", "value": "Disable"}).blocked

    def test_enable_means_allowed(self):
        assert not ScheduleEntry.from_api({"ID": "aa:bb", "value": "Enable"}).blocked

    def test_address_is_upper_cased(self):
        assert ScheduleEntry.from_api({"ID": "00:00:5e:00:53:03"}).mac == "00:00:5E:00:53:03"


class TestMissedCall:
    def test_timestamp_is_parsed(self):
        call = MissedCall.from_api({"startTime": "2026-09-09T11:05:10Z", "remoteNumber": "0102"})
        assert call.start_time is not None
        assert call.start_time.year == 2026

    def test_an_unparsable_timestamp_is_none(self):
        assert MissedCall.from_api({"startTime": "not a date"}).start_time is None


class TestUserAccount:
    def test_admin_group_is_detected(self):
        assert UserAccount.from_api({"name": "admin", "groups": ["http", "admin"]}).is_admin


class TestFunctionSignature:
    def test_str_reads_like_a_declaration(self):
        signature = FunctionSignature.from_api(
            {
                "name": "setDMZ",
                "type": "string",
                "arguments": [{"type": "string", "name": "id"}, {"type": "bool", "name": "enable"}],
            }
        )
        assert str(signature) == "setDMZ(string id, bool enable)"

    @pytest.mark.parametrize("name", ["setDMZ", "addUser", "deletePinhole", "commit", "enableSchedule"])
    def test_writing_methods_are_recognised(self, name):
        assert FunctionSignature(name=name, return_type="").writes

    @pytest.mark.parametrize("name", ["getDMZ", "listTrunks", "authenticate"])
    def test_reading_methods_are_not(self, name):
        assert not FunctionSignature(name=name, return_type="").writes
