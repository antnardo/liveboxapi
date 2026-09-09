"""Where the admin password comes from.

A router client is only as usable as its credential story. Hard-coding the
password is out of the question, prompting for it breaks unattended jobs, and a
config file in the home directory is one `chmod` away from a leak. This module
therefore resolves credentials from, in order: what the caller passed,
environment variables, and — for people who keep their secrets there — a
password manager invoked as a subprocess.

The password manager is called through its command-line tool rather than an
API: no extra dependency, no token to store, and the tool is already
authenticated on a workstation where the user is logged in.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace

from liveboxapi.errors import AuthenticationError

__all__ = ["DEFAULT_URL", "Credentials", "resolve_credentials"]

DEFAULT_URL = "http://192.168.1.1/"
"""Factory address of every Livebox. ``http://livebox.home/`` also works when mDNS does."""

_DEFAULT_USER = "admin"


@dataclass(frozen=True, slots=True)
class Credentials:
    """Everything needed to open a session."""

    url: str = DEFAULT_URL
    user: str = _DEFAULT_USER
    password: str = ""
    source: str = "explicit"
    """Which resolver produced these, for logging. Never contains the secret."""

    def __post_init__(self) -> None:
        if not self.url.endswith("/"):
            object.__setattr__(self, "url", self.url.rstrip("/") + "/")

    def __repr__(self) -> str:
        # A stray repr() in a log or a traceback must not leak the password.
        state = "set" if self.password else "empty"
        return (
            f"Credentials(url={self.url!r}, user={self.user!r}, password=<{state}>, source={self.source!r})"
        )


def _from_environment() -> Credentials | None:
    """``LIVEBOX_URL``, ``LIVEBOX_USER``, ``LIVEBOX_PASSWORD``.

    This is the path for services: a systemd unit with an ``EnvironmentFile``
    readable by root only, or a container's secret mount.
    """
    password = os.environ.get("LIVEBOX_PASSWORD")
    if not password:
        return None
    return Credentials(
        url=os.environ.get("LIVEBOX_URL", DEFAULT_URL),
        user=os.environ.get("LIVEBOX_USER", _DEFAULT_USER),
        password=password,
        source="environment",
    )


def _run_op(item: str, vault: str, timeout: float) -> str:
    """One invocation returning both fields as JSON.

    Reading the two fields separately doubles the latency and, more to the
    point, doubles the chance of hitting one of the tool's intermittent
    failures — measured at roughly one call in four on a service account,
    sometimes after a fourteen-second wait.
    """
    return subprocess.check_output(
        [
            "op",
            "item",
            "get",
            item,
            "--vault",
            vault,
            "--fields",
            "label=username,label=password",
            "--format",
            "json",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )


def _from_password_manager(timeout: float = 25.0, attempts: int = 2) -> Credentials | None:
    """1Password's ``op`` command line, driven by two environment variables.

    ``LIVEBOX_OP_ITEM`` holds the item — its name or its uuid — and
    ``LIVEBOX_OP_VAULT`` the vault, defaulting to ``Private``. The item is
    expected to carry a ``username`` and a ``password`` field, which is what the
    built-in "Login" template gives you.

    The call is retried once: the tool fails transiently often enough that a
    single attempt turns a working setup into an intermittent one. Returns
    ``None`` rather than raising when the tool is missing or the vault stays
    locked — this is one resolver among several, and the caller may well have
    another way in.
    """
    item = os.environ.get("LIVEBOX_OP_ITEM")
    if not item or shutil.which("op") is None:
        return None
    vault = os.environ.get("LIVEBOX_OP_VAULT", "Private")
    fields: dict[str, str] = {}
    for attempt in range(attempts):
        try:
            answer = _run_op(item, vault, timeout)
            parsed = json.loads(answer)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            if attempt + 1 == attempts:
                return None
            continue
        entries = parsed if isinstance(parsed, list) else [parsed]
        fields = {str(entry.get("label", "")): str(entry.get("value", "")) for entry in entries}
        break
    password = fields.get("password", "")
    if not password:
        return None
    return Credentials(
        url=os.environ.get("LIVEBOX_URL", DEFAULT_URL),
        user=fields.get("username") or _DEFAULT_USER,
        password=password,
        source="1password",
    )


#: Resolvers tried in order. Append to this list to teach the package about
#: another secret store; each callable returns ``Credentials`` or ``None``.
RESOLVERS: list[Callable[[], Credentials | None]] = [
    _from_environment,
    _from_password_manager,
]


def resolve_credentials(
    url: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> Credentials:
    """Return usable credentials, or raise.

    An explicit ``password`` short-circuits everything. Otherwise each resolver
    in :data:`RESOLVERS` is tried in turn, and ``url`` and ``user`` given here
    still override whatever it found — handy to reach a second box with the same
    stored password.
    """
    if password:
        return Credentials(
            url=url or os.environ.get("LIVEBOX_URL", DEFAULT_URL),
            user=user or _DEFAULT_USER,
            password=password,
            source="explicit",
        )
    for resolver in RESOLVERS:
        found = resolver()
        if found is None:
            continue
        overrides = {}
        if url:
            overrides["url"] = url
        if user:
            overrides["user"] = user
        return replace(found, **overrides) if overrides else found
    raise AuthenticationError(
        "no credentials found: pass password=..., set LIVEBOX_PASSWORD, "
        "or set LIVEBOX_OP_ITEM for the 1Password command line"
    )
