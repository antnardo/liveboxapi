"""Telephony: the call log, sorted and filtered."""

import pytest

from liveboxapi.voice import VoiceApi

LOG = [
    {"callType": "missed", "remoteNumber": "0101", "startTime": "2026-09-01T10:00:00Z", "viewed": True},
    {"callType": "missed", "remoteNumber": "0202", "startTime": "2026-09-08T18:30:00Z", "viewed": False},
    {"callType": "succeeded", "remoteNumber": "0303", "startTime": "2026-09-09T09:00:00Z"},
]


@pytest.fixture
def voice(session):
    return VoiceApi(session)


class TestMissedCalls:
    def test_only_missed_calls_are_kept(self, voice, http):
        http.enqueue({"status": LOG})
        assert [call.number for call in voice.missed_calls()] == ["0202", "0101"]

    def test_most_recent_first(self, voice, http):
        http.enqueue({"status": LOG})
        assert voice.missed_calls()[0].number == "0202"

    def test_the_limit_is_applied(self, voice, http):
        http.enqueue({"status": LOG})
        assert len(voice.missed_calls(limit=1)) == 1

    def test_unviewed_is_the_number_worth_alerting_on(self, voice, http):
        http.enqueue({"status": LOG})
        assert voice.unviewed_count() == 1

    def test_an_empty_log_is_not_an_error(self, voice, http):
        http.enqueue({"status": None})
        assert voice.missed_calls() == []

    def test_calls_without_a_date_do_not_break_sorting(self, voice, http):
        http.enqueue({"status": [{"callType": "missed", "remoteNumber": "0404"}]})
        assert voice.missed_calls()[0].number == "0404"


class TestLine:
    def test_the_first_enabled_line_wins(self, voice, http):
        http.enqueue(
            {
                "status": [
                    {
                        "trunk_lines": [
                            {"enable": "Disabled", "status": "Down"},
                            {"enable": "Enabled", "status": "Up"},
                        ]
                    }
                ]
            }
        )
        assert voice.line_status() == "Up"

    def test_no_line_reports_disabled(self, voice, http):
        http.enqueue({"status": []})
        assert voice.line_status() == "Disabled"
