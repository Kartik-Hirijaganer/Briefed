"""Chaos drill — Infisical secret rotation dry run.

Plan exit criterion: "secret-rotation dry run." Infisical rotates by
changing the injected environment for a new process or reload. The dry
run verifies that two uncached ``load_settings`` calls observe the new
value after reinjection, and that Lambda startup rejects a missing
required secret.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import load_settings

pytestmark = pytest.mark.chaos

_SECRET_ENV_ALIASES = (
    "BRIEFED_OPENROUTER_API_KEY",
    "OPENROUTER_API_KEY",
    "BRIEFED_SESSION_SIGNING_KEY",
    "SESSION_SIGNING_KEY",
    "GOOGLE_OAUTH_CLIENT_ID",
    "BRIEFED_GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "BRIEFED_GOOGLE_OAUTH_CLIENT_SECRET",
    "BRIEFED_DATABASE_URL",
    "DATABASE_URL",
)
"""Environment aliases controlled by the Infisical rotation drill."""


def _enable_lambda_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``Settings()`` to read the Lambda validation path.

    Args:
        monkeypatch: Pytest monkeypatch helper.
    """
    for name in _SECRET_ENV_ALIASES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")


def _inject_required_secrets(
    monkeypatch: pytest.MonkeyPatch,
    *,
    openrouter_api_key: str,
) -> None:
    """Inject a complete required secret set.

    Args:
        monkeypatch: Pytest monkeypatch helper.
        openrouter_api_key: OpenRouter value for this simulated rotation.
    """
    monkeypatch.setenv("BRIEFED_OPENROUTER_API_KEY", openrouter_api_key)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "sess-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "sec-1")
    monkeypatch.setenv("BRIEFED_DATABASE_URL", "postgresql+asyncpg://localhost/test")


def test_rotation_picks_up_new_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second settings load sees the rotated Infisical value."""
    _enable_lambda_runtime(monkeypatch)
    _inject_required_secrets(monkeypatch, openrouter_api_key="rot-1")

    first = load_settings()
    _inject_required_secrets(monkeypatch, openrouter_api_key="rot-2")
    second = load_settings()

    assert first.openrouter_api_key == "rot-1"
    assert second.openrouter_api_key == "rot-2"


def test_missing_required_secret_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing required Infisical values hard-fail Lambda startup."""
    _enable_lambda_runtime(monkeypatch)
    monkeypatch.setenv("SESSION_SIGNING_KEY", "sess-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "sec-1")
    monkeypatch.setenv("BRIEFED_DATABASE_URL", "postgresql+asyncpg://localhost/test")

    with pytest.raises(ValidationError):
        load_settings()
