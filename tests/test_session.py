"""Transport: authentication, in-band errors, read-only guard, batch, introspection."""

import pytest

from liveboxapi.errors import AuthenticationError, LiveboxError, ReadOnlyError
from liveboxapi.session import LiveboxSession


class TestLogin:
    def test_login_stores_the_context(self, http, credentials):
        http.enqueue({"data": {"contextID": "ctx-42"}})
        live = LiveboxSession(credentials, session=http)
        assert live.login() == "ctx-42"
        assert live.logged_in

    def test_login_without_context_raises(self, http, credentials):
        http.enqueue({"data": {}})
        live = LiveboxSession(credentials, session=http)
        with pytest.raises(AuthenticationError):
            live.login()

    def test_first_call_logs_in_by_itself(self, http, credentials):
        http.enqueue({"data": {"contextID": "ctx-1"}})
        http.enqueue({"status": "Medium"})
        live = LiveboxSession(credentials, session=http)
        live.call("Firewall", "getFirewallLevel")
        assert http.calls[0] == ("sah.Device.Information", "createContext")

    def test_context_is_sent_on_every_call(self, session, http):
        http.enqueue({"status": True})
        session.call("Firewall", "commit")
        assert http.posts[-1]["headers"]["X-Context"] == "ctx-1"

    def test_rejected_context_triggers_one_retry(self, session, http):
        http.enqueue({}, status_code=403)
        http.enqueue({"data": {"contextID": "ctx-2"}})
        http.enqueue({"status": "Medium"})
        assert session.call("Firewall", "getFirewallLevel") == "Medium"


class TestErrors:
    def test_in_band_error_raises(self, session, http):
        http.enqueue(
            {"status": None, "errors": [{"error": 196618, "description": "not found", "info": "Nope"}]}
        )
        with pytest.raises(LiveboxError) as caught:
            session.call("Nope", "get")
        assert caught.value.code == 196618

    def test_raw_returns_errors_without_raising(self, session, http):
        http.enqueue({"errors": [{"error": 393221, "description": "already reserved"}]})
        answer = session.raw("DHCPv4.Server.Pool.default", "addStaticLease")
        assert answer["errors"][0]["error"] == 393221

    def test_error_with_zero_code_is_not_an_error(self, session, http):
        # The box pads its error list with empty entries; only non-zero counts.
        http.enqueue({"status": "ok", "errors": [{"error": 0}]})
        assert session.call("Time", "getTime") == "ok"


class TestPayloadShape:
    def test_data_wins_when_it_is_a_mapping(self, session, http):
        http.enqueue({"status": None, "data": {"IPAddress": "1.2.3.4"}})
        assert session.call("NMC", "getWANStatus") == {"IPAddress": "1.2.3.4"}

    def test_status_is_used_when_there_is_no_data(self, session, http):
        http.enqueue({"status": [{"name": "admin"}]})
        assert session.call("UserManagement", "getUsers") == [{"name": "admin"}]

    def test_empty_data_falls_back_to_status(self, session, http):
        http.enqueue({"status": "Medium", "data": {}})
        assert session.call("Firewall", "getFirewallLevel") == "Medium"


class TestReadOnly:
    @pytest.mark.parametrize(
        "method", ["setFirewallLevel", "addStaticLease", "deleteDMZ", "commit", "enablePortForwarding"]
    )
    def test_writes_are_refused(self, http, credentials, method):
        live = LiveboxSession(credentials, readonly=True, session=http)
        with pytest.raises(ReadOnlyError):
            live.call("Firewall", method)

    def test_reads_still_work(self, http, credentials):
        http.enqueue({"data": {"contextID": "ctx"}})
        http.enqueue({"status": "Medium"})
        live = LiveboxSession(credentials, readonly=True, session=http)
        assert live.call("Firewall", "getFirewallLevel") == "Medium"

    def test_nothing_reaches_the_network(self, http, credentials):
        live = LiveboxSession(credentials, readonly=True, session=http)
        with pytest.raises(ReadOnlyError):
            live.call("Firewall", "setDMZ")
        assert http.posts == []


class TestBatch:
    def test_one_login_for_the_whole_batch(self, session, http):
        """The point of a batch: N calls, one authentication."""
        http.enqueue({"status": 1})
        http.enqueue({"status": 2})
        session.batch(
            [
                {"key": "a", "service": "S", "method": "getA"},
                {"key": "b", "service": "S", "method": "getB"},
            ]
        )
        assert http.calls.count(("sah.Device.Information", "createContext")) == 1

    def test_results_are_keyed(self, session, http):
        http.enqueue({"status": 1})
        http.enqueue({"status": 2})
        result = session.batch(
            [
                {"key": "first", "service": "S", "method": "getA"},
                {"key": "second", "service": "S", "method": "getB"},
            ]
        )
        assert result == {"first": {"status": 1}, "second": {"status": 2}}

    def test_key_defaults_to_service_and_method(self, session, http):
        http.enqueue({"status": 1})
        result = session.batch([{"service": "NMC", "method": "getWANStatus"}])
        assert "NMC:getWANStatus" in result

    def test_an_error_does_not_lose_the_other_answers(self, session, http):
        http.enqueue({"errors": [{"error": 196618, "description": "no"}]})
        http.enqueue({"status": "fine"})
        result = session.batch(
            [
                {"key": "broken", "service": "S", "method": "getA"},
                {"key": "ok", "service": "S", "method": "getB"},
            ]
        )
        assert result["ok"] == {"status": "fine"}


class TestIntrospection:
    def test_dotted_path_is_rewritten_with_slashes(self, session, http):
        """The trap: dots work for calls and give "permission denied" here."""
        http.enqueue({"functions": []})
        session.introspect("NMC.Wifi")
        assert http.gets[-1]["url"].endswith("/sysbus/NMC/Wifi")

    def test_session_headers_are_sent(self, session, http):
        http.enqueue({"functions": []})
        session.introspect("Firewall")
        assert http.gets[-1]["headers"]["Authorization"] == "X-Sah ctx-1"

    def test_depth_is_passed_through(self, session, http):
        http.enqueue({"functions": []})
        session.introspect("Firewall", depth=-1)
        assert http.gets[-1]["params"] == {"_restDepth": -1}

    def test_functions_are_parsed(self, session, http):
        http.enqueue(
            {
                "functions": [
                    {"name": "getDMZ", "type": "variant", "arguments": []},
                    {
                        "name": "setDMZ",
                        "type": "string",
                        "arguments": [{"type": "string", "name": "id"}],
                    },
                ]
            }
        )
        names = [f.name for f in session.functions("Firewall")]
        assert names == ["getDMZ", "setDMZ"]

    def test_writes_only_filters(self, session, http):
        http.enqueue(
            {
                "functions": [
                    {"name": "getDMZ", "type": "variant"},
                    {"name": "setDMZ", "type": "string"},
                    {"name": "commit", "type": "bool"},
                ]
            }
        )
        names = [f.name for f in session.functions("Firewall", writes_only=True)]
        assert names == ["setDMZ", "commit"]

    def test_parameters_are_flattened_to_a_mapping(self, session, http):
        http.enqueue({"parameters": [{"name": "Enable", "value": False}]})
        assert session.parameters("UPnP-IGD") == {"Enable": False}


class TestLifecycle:
    def test_context_manager_logs_in_and_out(self, http, credentials):
        http.enqueue({"data": {"contextID": "ctx"}})
        with LiveboxSession(credentials, session=http) as live:
            assert live.logged_in
        assert http.closed

    def test_repr_hides_everything_sensitive(self, session):
        assert "secret" not in repr(session)
