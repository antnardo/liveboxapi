"""Firewall: the selective commit, and the payloads the box is picky about."""

import pytest

from liveboxapi.firewall import PROTOCOL_TCP, PROTOCOL_UDP, FirewallApi


@pytest.fixture
def firewall(session):
    return FirewallApi(session)


class TestPortForwarding:
    def test_rules_are_parsed(self, firewall, http):
        http.enqueue(
            {
                "status": {
                    "webui_VPN": {
                        "Id": "webui_VPN",
                        "Origin": "webui",
                        "Protocol": "17",
                        "ExternalPort": "53134",
                        "InternalPort": "53134",
                        "DestinationIPAddress": "192.168.1.10",
                        "Enable": True,
                    }
                }
            }
        )
        rule = firewall.port_forwardings()["webui_VPN"]
        assert rule.destination == "192.168.1.10"
        assert rule.protocol_names == ("UDP",)

    def test_the_upnp_origin_can_be_asked_for(self, firewall, http):
        """An empty answer here is the check worth running: nothing opened itself."""
        http.enqueue({"status": {}})
        assert firewall.port_forwardings(origin="upnp") == {}
        assert http.last_parameters() == {"origin": "upnp"}

    def test_the_external_port_defaults_to_the_internal_one(self, firewall, http):
        http.enqueue({"status": "webui_Test"})
        http.enqueue({"status": True})
        firewall.set_port_forwarding("Test", "192.168.1.10", internal_port="443")
        sent = http.posts[-2]["body"]["parameters"]
        assert sent["externalPort"] == "443"

    def test_writing_a_rule_commits(self, firewall, http):
        """A rule that is stored but not committed exists nowhere useful."""
        http.enqueue({"status": "webui_Test"})
        http.enqueue({"status": True})
        firewall.set_port_forwarding("Test", "192.168.1.10", internal_port="80")
        assert http.calls[-1] == ("Firewall", "commit")

    def test_the_commit_can_be_deferred(self, firewall, http):
        http.enqueue({"status": "webui_Test"})
        firewall.set_port_forwarding("Test", "192.168.1.10", internal_port="80", commit=False)
        assert ("Firewall", "commit") not in http.calls

    def test_deletion_carries_the_origin(self, firewall, http):
        http.enqueue({"status": True})
        http.enqueue({"status": True})
        firewall.delete_port_forwarding("webui_VPN")
        assert http.posts[-2]["body"]["parameters"]["origin"] == "webui"


class TestPinholes:
    def test_ip_version_six_is_forced(self, firewall, http):
        http.enqueue({"status": "webui_ssh"})
        http.enqueue({"status": True})
        firewall.set_pinhole("ssh", "2001:db8::44", destination_port="22", protocol=PROTOCOL_TCP)
        assert http.posts[-2]["body"]["parameters"]["ipversion"] == 6

    def test_writing_a_pinhole_commits(self, firewall, http):
        http.enqueue({"status": "webui_ssh"})
        http.enqueue({"status": True})
        firewall.set_pinhole("ssh", "2001:db8::44", destination_port="22")
        assert http.calls[-1] == ("Firewall", "commit")


class TestNoCommitNeeded:
    """Levels, DMZ and ping apply immediately; committing them would be noise."""

    def test_setting_the_level_does_not_commit(self, firewall, http):
        http.enqueue({"status": True})
        firewall.set_level("Medium")
        assert ("Firewall", "commit") not in http.calls

    def test_deleting_a_dmz_does_not_commit(self, firewall, http):
        http.enqueue({"status": True})
        firewall.delete_dmz("webui_dmz")
        assert ("Firewall", "commit") not in http.calls

    def test_ping_is_sent_as_a_nested_pair(self, firewall, http):
        http.enqueue({"status": True})
        firewall.set_respond_to_ping(ipv4=False, ipv6=False)
        assert http.last_parameters() == {
            "sourceInterface": "data",
            "service_enable": {"enableIPv4": False, "enableIPv6": False},
        }


class TestUpnp:
    def test_reading_returns_a_boolean(self, firewall, http):
        http.enqueue({"status": {"Enable": False}})
        assert firewall.upnp_enabled() is False

    def test_writing_nests_the_argument_twice(self, firewall, http):
        """The declared parameter is itself called ``parameters``. Not a typo."""
        http.enqueue({"status": True})
        firewall.set_upnp(False)
        assert http.last_parameters() == {"parameters": {"Enable": False}}


class TestRemoteAccess:
    def test_disabling_takes_no_argument(self, firewall, http):
        http.enqueue({"status": True})
        firewall.disable_remote_access()
        assert http.calls[-1] == ("RemoteAccess", "disable")

    def test_enabling_returns_the_chosen_port(self, firewall, http):
        http.enqueue({"status": 51234})
        assert firewall.enable_remote_access(timeout=600) == 51234


class TestProtocols:
    def test_the_constants_are_iana_numbers(self):
        assert (PROTOCOL_TCP, PROTOCOL_UDP) == ("6", "17")
