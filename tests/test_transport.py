"""The malformed bodies this firmware emits, and how they are repaired.

Each case here is a body seen on real hardware, not an invented one.
"""

import pytest

from liveboxapi.errors import MalformedResponseError
from liveboxapi.transport import BodyDecoder

PERMISSION_DENIED = ',"errors":[{"error":13,"description":"Permission denied","info":""}]'


class FakeBody:
    def __init__(self, raw: bytes) -> None:
        self.content = raw


@pytest.fixture
def decoder() -> BodyDecoder:
    return BodyDecoder()


def body(text: str) -> FakeBody:
    return FakeBody(text.encode("utf-8"))


class TestValidBodies:
    def test_a_normal_object_is_returned_as_is(self, decoder):
        assert decoder.decode(body('{"status":true}')) == {"status": True}

    def test_a_list_body_is_returned_as_a_list(self, decoder):
        assert decoder.decode(body('[{"a":1},{"a":2}]')) == [{"a": 1}, {"a": 2}]

    def test_a_value_containing_the_concatenation_marker_is_untouched(self, decoder):
        # The repair for concatenated objects would corrupt this body. Parsing
        # first is what protects it: a valid document never reaches the repairs.
        assert decoder.decode(body('{"Name":"}{"}')) == {"Name": "}{"}


class TestPermissionDeniedEnvelope:
    def test_leading_comma_becomes_an_error_object(self, decoder):
        decoded = decoder.decode(body(PERMISSION_DENIED))
        assert decoded["errors"][0]["error"] == 13

    def test_the_description_survives(self, decoder):
        decoded = decoder.decode(body(PERMISSION_DENIED))
        assert decoded["errors"][0]["description"] == "Permission denied"


class TestOtherRepairs:
    def test_a_lone_comma_in_a_list_becomes_an_empty_list(self, decoder):
        assert decoder.decode(body('{"status":[,]}')) == {"status": []}

    def test_concatenated_objects_become_an_array(self, decoder):
        assert decoder.decode(body('{"a":1}{"a":2}')) == [{"a": 1}, {"a": 2}]


class TestUndecodableBodies:
    def test_an_html_error_page_raises(self, decoder):
        with pytest.raises(MalformedResponseError):
            decoder.decode(body("<html><body>400 Bad Request</body></html>"))

    def test_the_excerpt_is_kept_for_diagnosis(self, decoder):
        with pytest.raises(MalformedResponseError) as raised:
            decoder.decode(body("<html>nope</html>"))
        assert "nope" in raised.value.info

    def test_the_excerpt_is_truncated(self, decoder):
        with pytest.raises(MalformedResponseError) as raised:
            decoder.decode(body("<" * 5000))
        assert len(raised.value.info) <= MalformedResponseError.EXCERPT_LENGTH + 1


class TestEncoding:
    def test_invalid_utf8_does_not_break_the_reading(self, decoder):
        # Device names come from DHCP requests: whatever the device sent.
        raw = b'{"Name":"caf\xe9"}'
        assert decoder.decode(FakeBody(raw))["Name"].startswith("caf")
