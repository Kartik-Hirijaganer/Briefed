"""Unit tests for SSM secret hydration."""

from __future__ import annotations

import pytest

from app.integrations.ssm_secrets import MissingSecretError, fetch_parameters, merge_with_env


class FakeSsmClient:
    """Small fake for the SSM ``get_parameters`` API."""

    def __init__(self, values: dict[str, str]) -> None:
        """Store fake full-name values.

        Args:
            values: Mapping from full SSM path to parameter value.
        """
        self.values = values

    def get_parameters(
        self,
        *,
        Names: list[str],
        WithDecryption: bool,
    ) -> dict[str, object]:
        """Return fake SSM values for requested names."""
        assert WithDecryption is True
        return {
            "Parameters": [
                {"Name": name, "Value": self.values[name]} for name in Names if name in self.values
            ],
            "InvalidParameters": [name for name in Names if name not in self.values],
        }


def test_fetch_parameters_returns_short_name_values() -> None:
    """SSM full paths are mapped back to short names."""
    client = FakeSsmClient(
        {
            "/briefed/prod/openrouter_api_key": "openrouter",
            "/briefed/prod/supabase_url": "https://example.supabase.co",
        },
    )

    values = fetch_parameters(
        prefix="/briefed/prod",
        required=("openrouter_api_key",),
        optional=("supabase_url",),
        client=client,
    )

    assert values == {
        "openrouter_api_key": "openrouter",
        "supabase_url": "https://example.supabase.co",
    }


def test_fetch_parameters_rejects_missing_required_values() -> None:
    """Missing required names raise a deploy-blocking error."""
    client = FakeSsmClient({"/briefed/prod/openrouter_api_key": "PLACEHOLDER - set me"})

    with pytest.raises(MissingSecretError) as excinfo:
        fetch_parameters(
            prefix="/briefed/prod/",
            required=("openrouter_api_key", "session_signing_key"),
            client=client,
        )

    assert excinfo.value.missing == ("openrouter_api_key", "session_signing_key")


def test_merge_with_env_prefers_environment_values() -> None:
    """Environment values win over SSM values."""
    merged = merge_with_env(
        env={
            "BRIEFED_OPENROUTER_API_KEY": "env-openrouter",
            "SESSION_SIGNING_KEY": "env-session",
        },
        ssm_values={
            "openrouter_api_key": "ssm-openrouter",
            "session_signing_key": "ssm-session",
            "supabase_db_url": "postgresql+asyncpg://x@y/ssm",
        },
        field_to_ssm={
            "openrouter_api_key": "openrouter_api_key",
            "session_signing_key": "session_signing_key",
            "database_url": "supabase_db_url",
        },
    )

    assert merged == {
        "openrouter_api_key": "env-openrouter",
        "session_signing_key": "env-session",
        "database_url": "postgresql+asyncpg://x@y/ssm",
    }
