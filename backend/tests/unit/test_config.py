"""Unit tests for the Infisical-backed config contract.

The settings layer reads process environment only. Local Make targets and
deployments are responsible for injecting that environment from Infisical;
``.env`` files are allowed only for non-secret Infisical selector metadata.
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
    """Lambda startup hard-fails when required Infisical values are missing."""
    _clear_secret_aliases(monkeypatch)
    monkeypatch.setenv("BRIEFED_RUNTIME", "lambda-api")

    with pytest.raises(ValidationError) as excinfo:
        load_settings()

    message = str(excinfo.value)
    assert "Missing required Infisical-injected settings" in message
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
