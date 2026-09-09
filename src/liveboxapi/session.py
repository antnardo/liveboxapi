"""The transport: one session, many calls, and the datamodel behind them.

Two mechanisms in this file are not obvious from the wire format alone.

**Errors travel inside successful responses.** Every call returns HTTP 200. A
refusal is an ``errors`` list in the body, so :meth:`LiveboxSession.call` raises
on it rather than handing back a payload that looks fine.

**Introspection is a different protocol.** Calls are POSTed to ``/ws`` with the
service named in dotted form; the datamodel is read with GET on ``/sysbus/``
with the *same* path spelled with slashes, plus the session headers. Get either
detail wrong and the box answers "permission denied", which reads like an
authorisation problem and is not one. That trap is why so much tooling declares
introspection unavailable.
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any

import requests

from liveboxapi.credentials import Credentials, resolve_credentials
from liveboxapi.errors import AuthenticationError, LiveboxError, ReadOnlyError
from liveboxapi.models import FunctionSignature

__all__ = ["APP_NAME", "BatchCall", "LiveboxSession"]

APP_NAME = "so_sdkut"
"""Application name sent at login. The box logs it; any string is accepted."""

_LOGIN_HEADERS = {
    "Accept": "*/*",
    "Authorization": "X-Sah-Login",
    "Content-Type": "application/x-sah-ws-4-call+json",
}

_WRITE_PREFIXES = ("set", "add", "del", "remove", "create", "update", "enable", "disable", "commit")


class BatchCall(dict):
    """One entry of a batch, kept as a dict so callers can build them from JSON."""

    def __init__(
        self,
        service: str,
        method: str,
        parameters: Mapping[str, Any] | None = None,
        key: str | None = None,
    ) -> None:
        super().__init__(
            service=service,
            method=method,
            parameters=dict(parameters or {}),
            key=key or f"{service}:{method}",
        )


class LiveboxSession:
    """An authenticated conversation with one box.

    The session logs in lazily, on the first call, and re-authenticates once if
    the box drops the context — which it does after a reboot or a long idle.
    Callers therefore never have to think about the context lifetime.
    """

    def __init__(
        self,
        credentials: Credentials | None = None,
        *,
        readonly: bool = False,
        timeout: float | tuple[float, float] = (5.0, 15.0),
        session: requests.Session | None = None,
    ) -> None:
        self.credentials = credentials or resolve_credentials()
        self.readonly = readonly
        self.timeout = timeout
        self._http = session or requests.Session()
        self._context_id: str | None = None

    # ------------------------------------------------------------------ session

    @property
    def context_id(self) -> str | None:
        """The current context, or ``None`` before the first call."""
        return self._context_id

    @property
    def logged_in(self) -> bool:
        return self._context_id is not None

    def login(self) -> str:
        """Open a context. Called automatically; call it early to fail fast."""
        response = self._http.post(
            self.credentials.url + "ws",
            headers=_LOGIN_HEADERS,
            json={
                "service": "sah.Device.Information",
                "method": "createContext",
                "parameters": {
                    "applicationName": APP_NAME,
                    "username": self.credentials.user,
                    "password": self.credentials.password,
                },
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        context = (response.json().get("data") or {}).get("contextID")
        if not context:
            raise AuthenticationError(
                f"the box refused the credentials for user {self.credentials.user!r} "
                f"(source: {self.credentials.source})"
            )
        self._context_id = context
        return context

    def logout(self) -> None:
        """Drop the context and close the HTTP connection pool."""
        self._context_id = None
        self._http.close()

    def __enter__(self) -> "LiveboxSession":
        self.login()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.logout()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "Authorization": f"X-Sah {self._context_id}",
            "X-Context": self._context_id or "",
            "Content-Type": "application/x-sah-ws-4-call+json; charset=UTF-8",
        }

    # -------------------------------------------------------------------- calls

    def raw(
        self,
        service: str,
        method: str,
        parameters: Mapping[str, Any] | None = None,
        *,
        _retry: bool = True,
    ) -> dict:
        """Call a method and return the whole response, errors included.

        Use this when a non-zero error code is an expected outcome — creating a
        DHCP reservation that already exists, for instance, which the box
        reports as an error and which callers usually want to ignore.
        """
        if self._context_id is None:
            self.login()
        response = self._http.post(
            self.credentials.url + "ws",
            headers=self._headers(),
            json={"service": service, "method": method, "parameters": dict(parameters or {})},
            timeout=self.timeout,
        )
        if response.status_code in (401, 403) and _retry:
            self._context_id = None
            return self.raw(service, method, parameters, _retry=False)
        response.raise_for_status()
        return response.json()

    def call(
        self,
        service: str,
        method: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> Any:
        """Call a method, raise on refusal, and return the useful part.

        Answers put their payload in ``status`` or in ``data`` depending on the
        service, with no rule to predict which. Both are tried, ``data`` first
        when it is a mapping, because services that fill both put the richer
        content there.
        """
        self._guard(service, method)
        payload = self.raw(service, method, parameters)
        self._raise_on_error(payload, service, method)
        data = payload.get("data")
        status = payload.get("status")
        if isinstance(data, Mapping) and data:
            return data
        if status is not None:
            return status
        return data

    def batch(self, calls: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Run many calls in a single session and return ``{key: response}``.

        Opening a session costs a round trip and a password check, so reading
        twenty objects one process at a time is measured in minutes while the
        same twenty in one session take seconds. Each entry accepts ``service``,
        ``method`` and optionally ``parameters`` and ``key``.

        Responses are returned whole, errors included: a batch is usually an
        audit, and one unsupported method should not lose the other nineteen
        answers.
        """
        results: dict[str, Any] = {}
        for entry in calls:
            service, method = entry["service"], entry["method"]
            self._guard(service, method)
            key = entry.get("key") or f"{service}:{method}"
            results[key] = self.raw(service, method, entry.get("parameters") or {})
        return results

    def _guard(self, service: str, method: str) -> None:
        if self.readonly and method.startswith(_WRITE_PREFIXES):
            raise ReadOnlyError(service, method)

    @staticmethod
    def _raise_on_error(payload: Mapping[str, Any], service: str, method: str) -> None:
        errors = [e for e in payload.get("errors") or [] if e.get("error")]
        if not errors:
            return
        first = errors[0]
        raise LiveboxError(
            code=int(first.get("error", 0)),
            description=first.get("description", ""),
            info=first.get("info", ""),
            service=service,
            method=method,
        )

    # ------------------------------------------------------------ introspection

    def introspect(self, path: str, depth: int = 1) -> dict:
        """Read an object's own description: its parameters and its methods.

        ``path`` accepts either spelling — ``NMC.Wifi`` or ``NMC/Wifi`` — and is
        normalised here, because using dots on this endpoint is the classic way
        to get a misleading "permission denied".

        ``depth`` is the datamodel depth: 1 for the object itself, -1 for the
        whole subtree, which can be hundreds of kilobytes.
        """
        endpoint = self.credentials.url + "sysbus/" + path.replace(".", "/").strip("/")
        if self._context_id is None:
            self.login()
        response = self._http.get(
            endpoint,
            params={"_restDepth": depth},
            headers={
                "Accept": "*/*",
                "Authorization": f"X-Sah {self._context_id}",
                "X-Context": self._context_id or "",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        self._raise_on_error(payload, path, "introspect")
        return payload

    def functions(self, path: str, *, writes_only: bool = False) -> list[FunctionSignature]:
        """The methods an object exposes, with their signatures.

        This is the answer to "can I automate this setting?", read from the
        device rather than from documentation written for another model.
        """
        described = self.introspect(path).get("functions") or []
        signatures = [FunctionSignature.from_api(f) for f in described]
        return [s for s in signatures if s.writes] if writes_only else signatures

    def parameters(self, path: str) -> dict[str, Any]:
        """An object's parameters and their current values."""
        described = self.introspect(path).get("parameters") or []
        return {p.get("name"): p.get("value") for p in described if p.get("name")}

    def __repr__(self) -> str:
        state = "logged in" if self.logged_in else "not logged in"
        mode = ", read-only" if self.readonly else ""
        return f"<LiveboxSession {self.credentials.url} ({state}{mode})>"


def _json_default(value: object) -> str:  # pragma: no cover - debugging aid
    return json.dumps(str(value))
