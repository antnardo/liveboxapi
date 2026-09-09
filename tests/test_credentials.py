"""Credential resolution and, above all, not leaking the secret."""

import json

import pytest

from liveboxapi import credentials as module
from liveboxapi.credentials import Credentials, resolve_credentials
from liveboxapi.errors import AuthenticationError


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("LIVEBOX_URL", "LIVEBOX_USER", "LIVEBOX_PASSWORD", "LIVEBOX_OP_ITEM", "LIVEBOX_OP_VAULT"):
        monkeypatch.delenv(name, raising=False)


class TestCredentials:
    def test_url_always_ends_with_a_slash(self):
        assert Credentials(url="http://192.168.1.1").url == "http://192.168.1.1/"

    def test_repr_does_not_contain_the_password(self):
        text = repr(Credentials(password="hunter2"))
        assert "hunter2" not in text
        assert "<set>" in text


class TestResolution:
    def test_explicit_password_wins(self, monkeypatch):
        monkeypatch.setenv("LIVEBOX_PASSWORD", "from-env")
        found = resolve_credentials(password="explicit")
        assert found.password == "explicit"
        assert found.source == "explicit"

    def test_environment_is_used_next(self, monkeypatch):
        monkeypatch.setenv("LIVEBOX_PASSWORD", "from-env")
        monkeypatch.setenv("LIVEBOX_USER", "someone")
        found = resolve_credentials()
        assert (found.password, found.user, found.source) == ("from-env", "someone", "environment")

    def test_explicit_url_overrides_the_resolved_one(self, monkeypatch):
        monkeypatch.setenv("LIVEBOX_PASSWORD", "from-env")
        monkeypatch.setenv("LIVEBOX_URL", "http://one/")
        assert resolve_credentials(url="http://two/").url == "http://two/"

    def test_nothing_anywhere_raises(self):
        with pytest.raises(AuthenticationError, match="no credentials"):
            resolve_credentials()

    def test_a_custom_resolver_can_be_appended(self, monkeypatch):
        extra = Credentials(password="from-vault", source="vault")
        monkeypatch.setattr(module, "RESOLVERS", [lambda: extra])
        assert resolve_credentials().source == "vault"


class TestPasswordManager:
    def test_skipped_when_no_item_is_named(self, monkeypatch):
        monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/op")
        assert module._from_password_manager() is None

    def test_skipped_when_the_tool_is_missing(self, monkeypatch):
        monkeypatch.setenv("LIVEBOX_OP_ITEM", "Livebox")
        monkeypatch.setattr(module.shutil, "which", lambda _: None)
        assert module._from_password_manager() is None

    def test_both_fields_come_from_one_invocation(self, monkeypatch):
        """Two invocations double the latency and the chance of a transient failure."""
        monkeypatch.setenv("LIVEBOX_OP_ITEM", "Livebox")
        monkeypatch.setenv("LIVEBOX_OP_VAULT", "Home")
        monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/op")
        calls = []

        def fake_run(item, vault, timeout):
            calls.append((item, vault))
            return json.dumps(
                [
                    {"label": "username", "value": "admin"},
                    {"label": "password", "value": "s3cret"},
                ]
            )

        monkeypatch.setattr(module, "_run_op", fake_run)
        found = module._from_password_manager()
        assert found is not None
        assert (found.user, found.password) == ("admin", "s3cret")
        assert calls == [("Livebox", "Home")]

    def test_a_transient_failure_is_retried(self, monkeypatch):
        """The tool fails roughly one call in four; one attempt makes that our problem."""
        monkeypatch.setenv("LIVEBOX_OP_ITEM", "Livebox")
        monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/op")
        attempts = []

        def flaky(item, vault, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("transient")
            return json.dumps([{"label": "password", "value": "s3cret"}])

        monkeypatch.setattr(module, "_run_op", flaky)
        found = module._from_password_manager()
        assert found is not None and found.password == "s3cret"
        assert len(attempts) == 2

    def test_a_locked_vault_is_not_fatal(self, monkeypatch):
        monkeypatch.setenv("LIVEBOX_OP_ITEM", "Livebox")
        monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/op")

        def refuse(item, vault, timeout):
            raise OSError("locked")

        monkeypatch.setattr(module, "_run_op", refuse)
        assert module._from_password_manager() is None

    def test_unparsable_output_is_not_fatal(self, monkeypatch):
        monkeypatch.setenv("LIVEBOX_OP_ITEM", "Livebox")
        monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/op")
        monkeypatch.setattr(module, "_run_op", lambda item, vault, timeout: "not json")
        assert module._from_password_manager() is None
