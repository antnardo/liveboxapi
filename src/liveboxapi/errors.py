"""Exceptions raised by this package.

The box answers every call with HTTP 200, even when it refuses: the failure is
carried inside the JSON body, in an ``errors`` list. A caller that only checks
the HTTP status therefore believes a write succeeded when the box silently
dropped it. :class:`LiveboxError` exists to turn those in-band failures into
real exceptions, with the numeric code kept intact so callers can branch on it.
"""

__all__ = [
    "ERROR_ALREADY_RESERVED",
    "ERROR_NOT_FOUND",
    "ERROR_PERMISSION_DENIED",
    "AuthenticationError",
    "LiveboxError",
    "ReadOnlyError",
]

# Codes seen on Livebox 6, 7 and W7. They are stable across firmware versions,
# and the first two are common enough that callers routinely test for them.
ERROR_PERMISSION_DENIED = 13
ERROR_NOT_FOUND = 196618
"""Unknown service, method or object — also what a typo in a service name gives."""
ERROR_ALREADY_RESERVED = 393221
"""An identical DHCP reservation already exists. Not a real failure."""


class LiveboxError(Exception):
    """An error returned by the box inside an otherwise successful response.

    ``code`` and ``description`` come straight from the box; ``info`` usually
    names the object that was not found.
    """

    def __init__(
        self,
        code: int,
        description: str = "",
        info: str = "",
        service: str = "",
        method: str = "",
    ) -> None:
        self.code = code
        self.description = description
        self.info = info
        self.service = service
        self.method = method
        where = f"{service}:{method}" if service else "call"
        detail = f" ({info})" if info else ""
        super().__init__(f"{where} failed with {code}: {description}{detail}")


class AuthenticationError(LiveboxError):
    """``createContext`` did not return a context id: wrong password, or locked account."""

    def __init__(self, message: str = "authentication refused by the box") -> None:
        Exception.__init__(self, message)
        self.code = 0
        self.description = message
        self.info = ""
        self.service = "sah.Device.Information"
        self.method = "createContext"


class ReadOnlyError(RuntimeError):
    """A write was attempted on a session opened read-only.

    Writing to a home gateway is disruptive in ways that are hard to undo — a
    mistyped DHCP range takes the whole household off the network. Read-only
    sessions make "look, do not touch" the explicit default for monitoring
    code, so that a bug in a dashboard cannot reconfigure the router.
    """

    def __init__(self, service: str, method: str) -> None:
        super().__init__(
            f"{service}:{method} is a write and this session is read-only; "
            "open it with Livebox(..., readonly=False) to allow writes"
        )
