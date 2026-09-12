"""What the box actually sends, turned into JSON.

This firmware does not always emit valid JSON. Three malformations have been
observed, all of them on responses the box considers successful — HTTP 200,
correct content type, broken body:

``,"errors":[{"error":13,…}]``
    An error envelope missing its opening brace. Seen on objects the session is
    not allowed to read: ten of them on a Livebox W7, among the ``NeMo.Intf``
    templates. A strict parser raises a decode error here, so the caller learns
    "invalid JSON" instead of "permission denied" — the wrong diagnosis, and one
    that sends people looking for a bug in their own client.

``[,]``
    A list whose only element was dropped, leaving the separator behind. Seen in
    the answer to the global ``sysbus/*`` introspection request.

``}{``
    Two JSON objects concatenated with nothing between them, instead of an array.

The repairs below come from ``LmSession.py`` in LiveboxMonitor, which has carried
them for years; they are reimplemented here because nothing of that project is
vendored, and because an independent client meets exactly the same bodies. One
thing is done differently on purpose: the body is parsed *first* and repaired
only if that fails. Repairing unconditionally means scanning every response —
introspection answers reach 200 KB — and, worse, a device name or Wi-Fi key that
happens to contain ``}{`` would be silently corrupted inside an otherwise valid
document. A malformation always makes ``json.loads`` fail, so failure is the
correct trigger.
"""

import json
from typing import Any, Protocol

from liveboxapi.errors import MalformedResponseError

__all__ = ["BodyDecoder", "SupportsContent"]


class SupportsContent(Protocol):
    """Everything this decoder needs from a response: its bytes."""

    @property
    def content(self) -> bytes: ...


class BodyDecoder:
    """Parses a response body, repairing the malformations listed above.

    Stateless: one instance can serve a whole session, or the class can be used
    a call at a time.
    """

    def decode(self, response: SupportsContent) -> Any:
        """Return the parsed body, or raise :class:`MalformedResponseError`."""
        text = self.text(response)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass  # fall through: the body is broken, now try to repair it
        repaired = self.repair(text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise MalformedResponseError(repaired) from exc

    def text(self, response: SupportsContent) -> str:
        """Decode the bytes, replacing anything that is not UTF-8.

        A single bad byte in a device name — they come from DHCP requests, so
        they are whatever the device sent — must not take down a whole reading.
        """
        return response.content.decode("utf-8", errors="replace")

    def repair(self, text: str) -> str:
        """Apply the known repairs. Called only on a body that failed to parse."""
        text = text.replace("[,]", "[]")
        if text.startswith(',"errors":'):
            # Restore the braces so the envelope becomes a normal error object,
            # which the caller then reports as the refusal it is.
            return "{" + text[1:] + "}"
        if "}{" in text:
            return "[" + text.replace("}{", "},{") + "]"
        return text
