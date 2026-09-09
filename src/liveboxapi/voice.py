"""Telephony: the call log and the state of the line.

The box keeps its own call log, which is the only way to know about a missed
call from a script — the operator's voicemail lives on the network side and is
not exposed here.
"""

from typing import Any

from liveboxapi.models import MissedCall
from liveboxapi.session import LiveboxSession

__all__ = ["VoiceApi"]

_SERVICE = "VoiceService.VoiceApplication"


class VoiceApi:
    """Call log and line status."""

    def __init__(self, session: LiveboxSession) -> None:
        self._session = session

    def calls(self) -> list[dict[str, Any]]:
        """The raw call log, every direction and outcome."""
        return self._session.call(_SERVICE, "getCallList") or []

    def missed_calls(self, limit: int | None = None) -> list[MissedCall]:
        """Missed calls, most recent first."""
        missed = [MissedCall.from_api(c) for c in self.calls() if c.get("callType") == "missed"]
        missed.sort(key=lambda call: call.start_time or _EPOCH, reverse=True)
        return missed[:limit] if limit else missed

    def unviewed_count(self) -> int:
        """How many missed calls nobody has looked at — the number worth alerting on."""
        return sum(1 for call in self.missed_calls() if not call.viewed)

    def line_status(self) -> str:
        """``Up`` when the line is registered, ``Disabled`` when there is none."""
        for trunk in self._session.call(_SERVICE, "listTrunks") or []:
            for line in trunk.get("trunk_lines") or []:
                if line.get("enable") == "Enabled":
                    return str(line.get("status", ""))
        return "Disabled"


from datetime import UTC, datetime  # noqa: E402  - only used as a sort sentinel

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
