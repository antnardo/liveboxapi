"""Wi-Fi: interface names differ between models, so they are discovered."""

import pytest

from liveboxapi.errors import LiveboxError
from liveboxapi.wifi import BRIDGES, CANDIDATE_INTERFACES, WifiApi

_VAPS = {
    "status": {
        "wlanvap": {
            "vap2g0priv": {
                "SSID": "home",
                "VAPStatus": "Down",
                "Security": {"ModeEnabled": "WPA3-Personal-Compatibility"},
                "WPS": {"Enable": False},
            }
        }
    }
}
_NOT_FOUND = {"errors": [{"error": 196618, "description": "not found"}]}


@pytest.fixture
def wifi(session):
    return WifiApi(session)


class TestState:
    def test_switching_off_sends_both_fields(self, wifi, http):
        """Firmware that reads only one of them leaves the radios half-off."""
        http.enqueue({"status": True})
        wifi.set_enabled(False)
        assert http.last_parameters() == {"Enable": False, "Status": False}

    def test_wps_has_its_own_call(self, wifi, http):
        http.enqueue({"status": True})
        wifi.set_wps(False)
        assert http.calls[-1] == ("NMC.Wifi", "setWPSEnable")

    def test_guest_network_is_a_single_boolean(self, wifi, http):
        http.enqueue({"status": True})
        wifi.set_guest(False)
        assert http.last_parameters() == {"Enable": False}


class TestDiscovery:
    def test_the_bridges_answer_in_two_calls(self, wifi, http):
        """Ten probes cost seconds; asking the bridges costs two calls."""
        http.enqueue(_VAPS)
        http.enqueue(_NOT_FOUND)
        assert wifi.interface_names() == ("vap2g0priv",)
        assert len(http.posts) == 3  # login + two bridges

    def test_both_bridges_are_merged(self, wifi, http):
        http.enqueue(_VAPS)
        http.enqueue({"status": {"wlanvap": {"vap2g0guest": {"SSID": "guest"}}}})
        assert set(wifi.interface_names()) == {"vap2g0priv", "vap2g0guest"}

    def test_it_falls_back_to_probing_names(self, wifi, http):
        """Firmware where the bridges say nothing still has to work."""
        http.enqueue(_NOT_FOUND)
        http.enqueue(_NOT_FOUND)
        http.enqueue(_VAPS)
        for _ in range(len(CANDIDATE_INTERFACES) - 1):
            http.enqueue(_NOT_FOUND)
        assert wifi.interface_names() == ("vap2g0priv",)

    def test_the_result_is_cached(self, wifi, http):
        http.enqueue(_VAPS)
        http.enqueue(_NOT_FOUND)
        wifi.interface_names()
        before = len(http.posts)
        wifi.interfaces()
        assert len(http.posts) == before

    def test_refresh_forgets_the_cache(self, wifi, http):
        http.enqueue(_VAPS)
        http.enqueue(_NOT_FOUND)
        wifi.interface_names()
        before = len(http.posts)
        wifi.refresh()
        http.enqueue(_VAPS)
        http.enqueue(_NOT_FOUND)
        wifi.interface_names()
        assert len(http.posts) > before

    def test_interfaces_are_typed(self, wifi, http):
        http.enqueue(_VAPS)
        http.enqueue(_NOT_FOUND)
        interface = wifi.interfaces()[0]
        assert interface.uses_wpa3
        assert interface.band == "2.4GHz"
        assert not interface.wps_enabled

    def test_a_failing_probe_does_not_propagate(self, wifi, http):
        """Discovery swallows the error on purpose; a direct call still raises."""
        for _ in range(len(BRIDGES) + len(CANDIDATE_INTERFACES) + 1):
            http.enqueue(_NOT_FOUND)
        assert wifi.interface_names() == ()
        with pytest.raises(LiveboxError):
            wifi._session.call("NeMo.Intf.nope", "getMIBs")


class TestSecurity:
    def test_the_write_goes_to_the_lan_object(self, wifi, http):
        """Surprising but correct: not to the interface being changed."""
        http.enqueue({"status": True})
        wifi.set_security("vap2g0priv", "WPA3-Personal")
        assert http.calls[-1] == ("NeMo.Intf.lan", "setWLANConfig")

    def test_the_passphrase_is_only_sent_when_given(self, wifi, http):
        http.enqueue({"status": True})
        wifi.set_security("vap2g0priv", "WPA3-Personal")
        security = http.last_parameters()["mibs"]["wlanvap"]["vap2g0priv"]["Security"]
        assert "KeyPassPhrase" not in security

    def test_the_passphrase_is_sent_when_asked(self, wifi, http):
        http.enqueue({"status": True})
        wifi.set_security("vap2g0priv", "WPA3-Personal", passphrase="hunter2hunter2")
        security = http.last_parameters()["mibs"]["wlanvap"]["vap2g0priv"]["Security"]
        assert security["KeyPassPhrase"] == "hunter2hunter2"
