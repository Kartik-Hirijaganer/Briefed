"""Phase 0 exit-criteria tests for the config loader.

Covers:

* Local-mode loading returns a usable Settings even with no secrets.
* Lambda mode with a fake SSM client that returns every required
  parameter populates the Settings correctly.
* Lambda mode with a fake SSM client that returns an empty / partial
  result raises :class:`MissingSecretError` — this is the explicit
  "unit — config loader rejects missing SSM parameters" test listed
  in plan §14 Phase 0.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings, load_settings
from app.integrations.ssm_secrets import MissingSecretError


class _FakeSsm:
    """Minimal SSM stub that returns pre-baked values for ``get_parameters``."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.calls: list[list[str]] = []

    def get_parameters(
        self,
        *,
        Names: list[str],
        WithDecryption: bool,  # matches boto3 signature; value irrelevant for the stub
    ) -> dict[str, Any]:
        self.calls.append(list(Names))
        return {
            "Parameters": [
                {"Name": name, "Value": self._values[name]}
                for name in Names
                if name in self._values
            ],
        }


def _required_ssm_payload(prefix: str) -> dict[str, str]:
    """Build a mapping of required SSM param names → non-placeholder values."""
    return {
        f"{prefix}gemini_api_key": "fake-gemini",
        f"{prefix}session_signing_key": "fake-session",
        f"{prefix}google_oauth_client_id": "fake-client-id",
        f"{prefix}google_oauth_client_secret": "fake-client-secret",
        f"{prefix}supabase_db_url": "postgresql+asyncpg://x@y/z",
    }


def test_local_runtime_does_not_hit_ssm(monkeypatch: pytest.MonkeyPatch) -> None:
    """In local mode the loader never constructs an SSM client."""
    monkeypatch.setenv("BRIEFED_RUNTIME", "local")
    monkeypatch.delenv("BRIEFED_SSM_PREFIX", raising=False)

    # Sentinel that would explode if invoked — proves we never touched it.
    class _Boom:
        def get_parameters(self, **_: object) -> dict[str, Any]:
            raise AssertionError("SSM client was invoked in local mode")

    settings = load_settings(ssm_client=_Boom())
    assert isinstance(settings, Settings)
    assert settings.runtime == "local"


def test_lambda_runtime_without_prefix_is_local_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``BRIEFED_SSM_PREFIX`` is unset the Lambda never tries to hydrate.

    This guards against a half-configured env silently booting with empty
    secrets — callers still check ``settings.gemini_api_key is not None``
    downstream, so local semantics are the safe default.
    """
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")
    monkeypatch.delenv("BRIEFED_SSM_PREFIX", raising=False)

    settings = load_settings()
    assert settings.ssm_prefix is None
    assert settings.gemini_api_key is None


def test_lambda_runtime_hydrates_from_ssm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Required SSM params resolve into the Settings fields."""
    prefix = "/briefed/dev/"
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")
    monkeypatch.setenv("BRIEFED_SSM_PREFIX", prefix)
    # Clear stray local values so SSM wins the merge.
    for var in (
        "GEMINI_API_KEY",
        "SESSION_SIGNING_KEY",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "BRIEFED_DATABASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    fake = _FakeSsm(_required_ssm_payload(prefix))
    settings = load_settings(ssm_client=fake, env={})

    assert settings.gemini_api_key == "fake-gemini"
    assert settings.session_signing_key == "fake-session"
    assert settings.google_oauth_client_id == "fake-client-id"
    assert settings.google_oauth_client_secret == "fake-client-secret"
    assert settings.database_url == "postgresql+asyncpg://x@y/z"


def test_lambda_runtime_rejects_missing_required_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 0 exit-criteria: loader raises when any required SSM param is absent.

    Drops every required parameter from the SSM response and asserts that
    :class:`MissingSecretError` surfaces with every missing short-name.
    """
    prefix = "/briefed/dev/"
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")
    monkeypatch.setenv("BRIEFED_SSM_PREFIX", prefix)

    fake = _FakeSsm({})  # No values at all — every required name is missing.

    with pytest.raises(MissingSecretError) as excinfo:
        load_settings(ssm_client=fake, env={})

    missing = set(excinfo.value.missing)
    # The five required short-names declared in app.core.config._REQUIRED_SECRETS.
    assert missing == {
        "gemini_api_key",
        "session_signing_key",
        "google_oauth_client_id",
        "google_oauth_client_secret",
        "supabase_db_url",
    }


def test_lambda_runtime_rejects_placeholder_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terraform-placeholder strings are treated as 'missing' by the loader.

    The SSM module seeds every parameter with a ``PLACEHOLDER — set via
    aws ssm put-parameter --overwrite`` value so Terraform can own the
    parameter name without committing a real secret. The loader must
    reject those values with the same error path as an absent parameter.
    """
    prefix = "/briefed/dev/"
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")
    monkeypatch.setenv("BRIEFED_SSM_PREFIX", prefix)

    placeholder = "PLACEHOLDER — set via aws ssm put-parameter --overwrite"
    payload = {name: placeholder for name in _required_ssm_payload(prefix)}
    fake = _FakeSsm(payload)

    with pytest.raises(MissingSecretError):
        load_settings(ssm_client=fake, env={})
