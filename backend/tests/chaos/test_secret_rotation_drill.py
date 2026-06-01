"""Chaos drill — secret rotation dry run (plan §14 Phase 8 + §20.6).

Plan exit criterion: "secret-rotation dry run." We exercise the SSM
hydration path with a stubbed ``ssm:GetParameters`` client whose return
value rotates between two distinct secret values across two consecutive
``load_settings`` calls. The dry run must:

* Pick up the new value on the second load.
* Refuse to start when a required parameter is missing or holds the
  Terraform placeholder.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import load_settings
from app.integrations.ssm_secrets import MissingSecretError

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
"""Environment aliases that must not override the SSM rotation stub."""


class _RotatingSsm:
    """SSM stub whose ``openrouter_api_key`` rotates per call."""

    def __init__(self, prefix: str, values: list[dict[str, str]]) -> None:
        self.prefix = prefix
        self.values = values
        self.calls = 0

    def get_parameters(
        self,
        *,
        Names: list[str],
        WithDecryption: bool,
    ) -> dict[str, Any]:
        idx = min(self.calls, len(self.values) - 1)
        self.calls += 1
        current = self.values[idx]
        params = []
        invalid = []
        for name in Names:
            short = name[len(self.prefix) :]
            if short in current:
                params.append({"Name": name, "Value": current[short]})
            else:
                invalid.append(name)
        return {"Parameters": params, "InvalidParameters": invalid}


def _enable_lambda_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``Settings()`` to read the lambda-runtime hydration path."""
    for name in _SECRET_ENV_ALIASES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")
    monkeypatch.setenv("BRIEFED_SSM_PREFIX", "/briefed/test/")


def test_rotation_picks_up_new_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """The second hydration sees the rotated value, not the cached first one."""
    _enable_lambda_runtime(monkeypatch)
    pre = {
        "openrouter_api_key": "rot-1",
        "session_signing_key": "sess-1",
        "google_oauth_client_id": "id-1",
        "google_oauth_client_secret": "sec-1",
        "supabase_db_url": "postgresql+asyncpg://localhost/test",
    }
    post = dict(pre, openrouter_api_key="rot-2")
    ssm = _RotatingSsm(prefix="/briefed/test/", values=[pre, post])

    first = load_settings(ssm_client=ssm)
    second = load_settings(ssm_client=ssm)

    assert first.openrouter_api_key == "rot-1"
    assert second.openrouter_api_key == "rot-2"
    assert ssm.calls == 2, "rotation drill must invoke ssm twice"


def test_missing_required_secret_raises_missing_secret_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placeholder values for a required field hard-fail the load."""
    _enable_lambda_runtime(monkeypatch)
    bad = {
        "session_signing_key": "sess-1",
        "google_oauth_client_id": "id-1",
        "google_oauth_client_secret": "sec-1",
        "supabase_db_url": "postgresql+asyncpg://localhost/test",
        # openrouter_api_key intentionally missing.
    }
    ssm = _RotatingSsm(prefix="/briefed/test/", values=[bad])
    with pytest.raises(MissingSecretError):
        load_settings(ssm_client=ssm)
