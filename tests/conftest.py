"""A recorded transport, so the suite never needs a router.

`requests` is replaced by a stub that answers from a queue and remembers what it
was asked. Two things follow: the tests assert on the exact payload sent — which
is where this API's traps live, uppercase addresses and nested arguments — and
they run anywhere, including in continuous integration.
"""

import json

import pytest

from liveboxapi.credentials import Credentials
from liveboxapi.session import LiveboxSession


class FakeResponse:
    """A response the decoder can read: bytes, not a parsed object.

    ``body`` bypasses serialisation so a test can hand over exactly what the
    firmware sends, malformations included.
    """

    def __init__(
        self,
        payload: dict | list | None = None,
        status_code: int = 200,
        body: str | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = body if body is not None else json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def json(self) -> dict | list | None:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


class FakeHTTP:
    """Stands in for ``requests.Session``.

    ``queue`` holds the answers to give, in order; once empty, ``default`` is
    returned. Every request is appended to ``posts`` or ``gets``.
    """

    def __init__(self, default: dict | None = None) -> None:
        self.queue: list[FakeResponse] = []
        self.default = default if default is not None else {"status": None}
        self.posts: list[dict] = []
        self.gets: list[dict] = []
        self.closed = False

    def enqueue(self, payload: dict | list, status_code: int = 200) -> None:
        self.queue.append(FakeResponse(payload, status_code))

    def enqueue_body(self, body: str, status_code: int = 200) -> None:
        """Queue a raw body, for the malformed answers this firmware sends."""
        self.queue.append(FakeResponse(body=body, status_code=status_code))

    def post(self, url, headers=None, json=None, timeout=None, verify=None):
        self.posts.append({"url": url, "headers": headers or {}, "body": json or {}, "verify": verify})
        return self.queue.pop(0) if self.queue else FakeResponse(self.default)

    def get(self, url, params=None, headers=None, timeout=None, verify=None):
        self.gets.append({"url": url, "params": params or {}, "headers": headers or {}, "verify": verify})
        return self.queue.pop(0) if self.queue else FakeResponse(self.default)

    def close(self) -> None:
        self.closed = True

    @property
    def calls(self) -> list[tuple[str, str]]:
        """``(service, method)`` of every call, in order — the usual assertion."""
        return [(p["body"].get("service"), p["body"].get("method")) for p in self.posts]

    def last_parameters(self) -> dict:
        return self.posts[-1]["body"].get("parameters", {})


@pytest.fixture
def http() -> FakeHTTP:
    return FakeHTTP()


@pytest.fixture
def credentials() -> Credentials:
    return Credentials(url="http://box.test/", user="admin", password="secret", source="test")


@pytest.fixture
def session(http: FakeHTTP, credentials: Credentials) -> LiveboxSession:
    """A logged-in session: the login answer is pre-loaded so tests can ignore it."""
    http.enqueue({"data": {"contextID": "ctx-1"}})
    live = LiveboxSession(credentials, session=http)
    live.login()
    return live
