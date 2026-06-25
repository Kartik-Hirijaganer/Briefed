"""Unit tests for the runtime config contract.

Local Make targets inject environment from Infisical. Lambda deployments may
hydrate missing secrets from SSM SecureString parameters created by Terraform.
``.env`` files are allowed only for non-secret selector metadata.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, load_settings

_SECRET_ENV_ALIASES: tuple[str, ...] = (
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
"""Application secret aliases that must not be read from ``.env``."""


def _clear_secret_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove secret aliases from the current test process.

    Args:
        monkeypatch: Pytest monkeypatch helper.
    """
    for name in _SECRET_ENV_ALIASES:
        monkeypatch.delenv(name, raising=False)


def _inject_required_lambda_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject the minimum required Lambda secret set.

    Args:
        monkeypatch: Pytest monkeypatch helper.
    """
    monkeypatch.setenv("BRIEFED_OPENROUTER_API_KEY", "fake-openrouter")
    monkeypatch.setenv("SESSION_SIGNING_KEY", "fake-session")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("BRIEFED_DATABASE_URL", "postgresql+asyncpg://x@y/z")


def test_local_runtime_is_usable_without_live_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local tests can construct settings without live Infisical credentials."""
    _clear_secret_aliases(monkeypatch)
    monkeypatch.setenv("BRIEFED_RUNTIME", "local")

    settings = load_settings()

    assert isinstance(settings, Settings)
    assert settings.runtime == "local"
    assert settings.openrouter_api_key is None


def test_dotenv_file_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stale local ``.env`` file cannot supply application secrets."""
    _clear_secret_aliases(monkeypatch)
    monkeypatch.chdir(tmp_path)
    tmp_path.joinpath(".env").write_text(
        "\n".join(
            (
                "BRIEFED_OPENROUTER_API_KEY=from-dotenv",
                "BRIEFED_DATABASE_URL=postgresql+asyncpg://x@y/dotenv",
            ),
        ),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.openrouter_api_key is None
    assert settings.database_url is None


def test_reads_infisical_injected_secret_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Settings accept the env names injected by ``infisical run``."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BRIEFED_RUNTIME", "local")
    monkeypatch.setenv("BRIEFED_ENV", "dev")
    monkeypatch.setenv("BRIEFED_OPENROUTER_API_KEY", "fake-openrouter-env")
    monkeypatch.setenv("BRIEFED_DATABASE_URL", "postgresql+asyncpg://x@y/env")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = load_settings()

    assert settings.env == "dev"
    assert settings.openrouter_api_key == "fake-openrouter-env"
    assert settings.database_url == "postgresql+asyncpg://x@y/env"


def test_reads_infisical_selector_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Infisical project metadata is part of typed settings."""
    monkeypatch.setenv("BRIEFED_INFISICAL_PROJECT_ID", "project-id")
    monkeypatch.setenv("BRIEFED_INFISICAL_ENVIRONMENT", "prod")
    monkeypatch.setenv("BRIEFED_INFISICAL_SECRET_PATH", "/production")

    settings = load_settings()

    assert settings.secrets_provider == "infisical"
    assert settings.infisical_project_id == "project-id"
    assert settings.infisical_environment == "prod"
    assert settings.infisical_secret_path == "/production"


def test_lambda_runtime_requires_infisical_injected_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lambda startup hard-fails when required runtime values are missing."""
    _clear_secret_aliases(monkeypatch)
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")

    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    message = str(excinfo.value)
    assert "Missing required runtime settings" in message
    assert "openrouter_api_key" in message
    assert "database_url" in message


def test_lambda_runtime_accepts_complete_infisical_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lambda startup succeeds with the required Infisical secret set."""
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")
    _inject_required_lambda_settings(monkeypatch)

    settings = load_settings()

    assert settings.runtime == "lambda-api"
    assert settings.openrouter_api_key == "fake-openrouter"
    assert settings.database_url == "postgresql+asyncpg://x@y/z"


def test_lambda_runtime_hydrates_missing_secrets_from_ssm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lambda startup fills missing required secrets from SSM."""
    import app.core.config as config_module

    _clear_secret_aliases(monkeypatch)
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")
    monkeypatch.setenv("BRIEFED_SSM_PREFIX", "/briefed/prod/")

    def fake_fetch_parameters(
        *,
        prefix: str,
        required: tuple[str, ...],
        optional: tuple[str, ...],
    ) -> dict[str, str]:
        assert prefix == "/briefed/prod/"
        assert set(required) == {
            "openrouter_api_key",
            "session_signing_key",
            "google_oauth_client_id",
            "google_oauth_client_secret",
            "supabase_db_url",
        }
        assert set(optional) == {"supabase_url", "supabase_service_key"}
        return {
            "openrouter_api_key": "ssm-openrouter",
            "session_signing_key": "ssm-session",
            "google_oauth_client_id": "ssm-client-id",
            "google_oauth_client_secret": "ssm-client-secret",
            "supabase_db_url": "postgresql+asyncpg://x@y/ssm",
            "supabase_url": "https://example.supabase.co",
        }

    monkeypatch.setattr(config_module, "fetch_parameters", fake_fetch_parameters)

    settings = load_settings()

    assert settings.openrouter_api_key == "ssm-openrouter"
    assert settings.session_signing_key == "ssm-session"
    assert settings.database_url == "postgresql+asyncpg://x@y/ssm"
    assert settings.supabase_url == "https://example.supabase.co"


def test_lambda_runtime_prefers_env_over_ssm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct env injection wins over SSM when both provide a value."""
    import app.core.config as config_module

    _clear_secret_aliases(monkeypatch)
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")
    monkeypatch.setenv("BRIEFED_SSM_PREFIX", "/briefed/prod/")
    monkeypatch.setenv("BRIEFED_OPENROUTER_API_KEY", "env-openrouter")

    def fake_fetch_parameters(
        *,
        prefix: str,
        required: tuple[str, ...],
        optional: tuple[str, ...],
    ) -> dict[str, str]:
        del prefix, optional
        assert "openrouter_api_key" not in required
        return {
            "session_signing_key": "ssm-session",
            "google_oauth_client_id": "ssm-client-id",
            "google_oauth_client_secret": "ssm-client-secret",
            "supabase_db_url": "postgresql+asyncpg://x@y/ssm",
        }

    monkeypatch.setattr(config_module, "fetch_parameters", fake_fetch_parameters)

    settings = load_settings()

    assert settings.openrouter_api_key == "env-openrouter"
    assert settings.session_signing_key == "ssm-session"
