"""Typed application settings for Infisical-injected runtime configuration.

Briefed treats Infisical as the single source of truth for application
secrets. Local developer commands fetch secrets through ``infisical run``;
production deploys must inject the same environment variables from
Infisical before the Python process starts. The settings layer deliberately
does **not** read ``.env`` files, so stale local files cannot shadow
Infisical values.

Tests may still monkeypatch process environment variables directly. That
keeps unit tests hermetic without reintroducing a second secret source for
real runtime paths.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Literal, Self, cast

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.integrations.ssm_secrets import fetch_parameters, merge_with_env

Runtime = Literal["local", "lambda-api", "lambda-worker", "lambda-fanout"]
"""The deployment shape the current process is serving."""

_REQUIRED_LAMBDA_SECRET_FIELDS: tuple[str, ...] = (
    "openrouter_api_key",
    "session_signing_key",
    "google_oauth_client_id",
    "google_oauth_client_secret",
    "database_url",
)
"""Fields that must be present before any Lambda runtime can start."""

_SSM_PARAMETER_BY_FIELD: dict[str, str] = {
    "openrouter_api_key": "openrouter_api_key",
    "session_signing_key": "session_signing_key",
    "google_oauth_client_id": "google_oauth_client_id",
    # This value names an SSM parameter; it is not secret material.
    "google_oauth_client_secret": "google_oauth_client_secret",  # nosec B105
    "database_url": "supabase_db_url",
}
"""Settings field to SSM short-name mapping for required Lambda secrets."""

_OPTIONAL_SSM_PARAMETER_BY_FIELD: dict[str, str] = {
    "supabase_url": "supabase_url",
    "supabase_service_key": "supabase_service_key",
}
"""Settings field to SSM short-name mapping for optional Lambda secrets."""

_PLACEHOLDER_PREFIX = "PLACEHOLDER"
"""Prefix used by Terraform-owned placeholder SecureString values."""


class Settings(BaseSettings):
    """Typed application settings.

    Attributes cover three buckets: runtime identity (``env`` /
    ``runtime``), Infisical selection metadata, and application values
    already injected into the process by Infisical.

    Uses process environment only. Unknown env vars are ignored because
    Docker, LocalStack, AWS, and Infisical all contribute extra names.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    env: str = Field(
        default="local",
        description="Environment slug (local/dev/prod).",
        validation_alias=AliasChoices("BRIEFED_ENV", "ENV"),
    )
    runtime: Runtime = Field(
        default="local",
        description="Which deployment surface this process is serving.",
        validation_alias="BRIEFED_RUNTIME",
    )
    log_level: str = Field(default="info", description="Minimum log level name.")

    public_base_url: str | None = Field(
        default=None,
        description=(
            "Public browser-facing origin used for OAuth callbacks when the API runs behind "
            "CloudFront or another reverse proxy."
        ),
        validation_alias="BRIEFED_PUBLIC_BASE_URL",
    )

    secrets_provider: Literal["infisical"] = Field(
        default="infisical",
        description="Secret provider. Briefed supports Infisical only.",
        validation_alias="BRIEFED_SECRETS_PROVIDER",
    )
    infisical_project_id: str | None = Field(
        default=None,
        description="Infisical project id used by local Make targets and deployments.",
        validation_alias="BRIEFED_INFISICAL_PROJECT_ID",
    )
    infisical_environment: str = Field(
        default="dev",
        description="Infisical environment slug selected by local Make targets.",
        validation_alias="BRIEFED_INFISICAL_ENVIRONMENT",
    )
    infisical_secret_path: str = Field(
        default="/development",
        description="Infisical secret path selected by local Make targets.",
        validation_alias="BRIEFED_INFISICAL_SECRET_PATH",
    )
    ssm_prefix: str | None = Field(
        default=None,
        description="SSM SecureString prefix used by Lambda runtimes.",
        validation_alias="BRIEFED_SSM_PREFIX",
    )

    database_url: str | None = Field(
        default=None,
        description="SQLAlchemy async URL (asyncpg driver).",
        validation_alias=AliasChoices("BRIEFED_DATABASE_URL", "DATABASE_URL"),
    )

    # Secrets (nullable so local / CI startup is possible without them).
    openrouter_api_key: str | None = Field(
        default=None,
        description="OpenRouter API key — required in Lambda runtimes (ADR 0009).",
        validation_alias=AliasChoices("BRIEFED_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
    )
    google_oauth_client_id: str | None = Field(
        default=None,
        description="Google OAuth client id for Gmail authorization-code flow.",
        validation_alias=AliasChoices("GOOGLE_OAUTH_CLIENT_ID", "BRIEFED_GOOGLE_OAUTH_CLIENT_ID"),
    )
    google_oauth_client_secret: str | None = Field(
        default=None,
        description="Google OAuth client secret for Gmail authorization-code flow.",
        validation_alias=AliasChoices(
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "BRIEFED_GOOGLE_OAUTH_CLIENT_SECRET",
        ),
    )
    session_signing_key: str | None = Field(
        default=None,
        description="HMAC secret used to sign local session and OAuth-state cookies.",
        validation_alias=AliasChoices("SESSION_SIGNING_KEY", "BRIEFED_SESSION_SIGNING_KEY"),
    )
    supabase_url: str | None = Field(
        default=None,
        description="Supabase project URL for optional file-storage access.",
        validation_alias=AliasChoices("SUPABASE_URL", "BRIEFED_SUPABASE_URL"),
    )
    supabase_service_key: str | None = Field(
        default=None,
        description="Supabase service-role key for optional file-storage access.",
        validation_alias=AliasChoices("SUPABASE_SERVICE_KEY", "BRIEFED_SUPABASE_SERVICE_KEY"),
    )

    # ADR 0009 — daily USD spend cap.
    daily_llm_usd_cap: float | None = Field(
        default=None,
        description=(
            "Hard cap on total LLM USD spend per UTC day (ADR 0009). "
            "None disables. When the cap is reached, LLMClient raises "
            "LLMBudgetExceededError and trips a global breaker until "
            "the next UTC midnight."
        ),
        validation_alias="BRIEFED_DAILY_LLM_USD_CAP",
    )

    # Crypto / KMS alias names (read via env; Terraform injects them).
    token_wrap_key_alias: str | None = Field(
        default=None,
        validation_alias="BRIEFED_TOKEN_WRAP_KEY_ALIAS",
    )
    content_key_alias: str | None = Field(
        default=None,
        validation_alias="BRIEFED_CONTENT_KEY_ALIAS",
    )

    # Phase 8 — observability + error reporting.
    otel_exporter: Literal["none", "console", "otlp"] = Field(
        default="none",
        description=(
            "OpenTelemetry span exporter ('none' for tests/local; 'otlp' wires the ADOT collector)."
        ),
        validation_alias="BRIEFED_OTEL_EXPORTER",
    )
    sentry_dsn: str | None = Field(
        default=None,
        description="Sentry DSN; when unset, error reporting is a no-op (test + local default).",
        validation_alias="BRIEFED_SENTRY_DSN",
    )
    sentry_traces_sample_rate: float = Field(
        default=0.05,
        description="Sentry transaction sample rate; 5% in prod, 0 in tests.",
        validation_alias="BRIEFED_SENTRY_TRACES_SAMPLE_RATE",
    )
    manual_run_daily_cap: int = Field(
        default=10,
        description="Per-user manual-trigger cap (rolling 24h). Plan §19.16 + §20.2.",
        validation_alias="BRIEFED_MANUAL_RUN_DAILY_CAP",
    )
    unsubscribe_execute_timeout_seconds: float = Field(
        default=10.0,
        gt=0.0,
        description=(
            "Per-request timeout (seconds) for the SSRF-hardened unsubscribe "
            "executor's outbound List-Unsubscribe POST (ADR 0014). Operational "
            "tunable only — the execute capability itself is gated by "
            "FeatureConfig.unsubscribe_execute, not by this value."
        ),
        validation_alias="BRIEFED_UNSUBSCRIBE_EXECUTE_TIMEOUT_SECONDS",
    )

    # LLM prompt redaction. Presidio was removed in the Phase 2 daily
    # triage revamp; setting this true now fails fast when the chain is built.
    redaction_presidio_enabled: bool = Field(
        default=False,
        description=(
            "Legacy Presidio toggle. Presidio support was removed; "
            "keep this false and use identity + regex scrubbers."
        ),
        validation_alias="BRIEFED_REDACTION_PRESIDIO_ENABLED",
    )
    # Identity-scrubber fallback envs (Phase 7). Track C will swap the
    # IdentityScrubber construction site to read from the user-profile
    # row; until then settings/env feed the chain.
    user_email: str | None = Field(
        default=None,
        description="User's primary email; folded into <USER_EMAIL>.",
        validation_alias="BRIEFED_USER_EMAIL",
    )
    user_name: str | None = Field(
        default=None,
        description="User's display name; folded into <USER_NAME>.",
        validation_alias="BRIEFED_USER_NAME",
    )
    user_aliases: str | None = Field(
        default=None,
        description=("Comma-separated aliases / nicknames merged into <USER_NAME>."),
        validation_alias="BRIEFED_USER_ALIASES",
    )

    @model_validator(mode="after")
    def require_lambda_secrets(self) -> Self:
        """Reject Lambda startup when Infisical did not inject required secrets.

        Returns:
            The validated settings instance.

        Raises:
            ValueError: If a Lambda runtime is missing required secret fields.
        """
        if not self.runtime.startswith("lambda-"):
            return self

        missing = [
            field_name
            for field_name in _REQUIRED_LAMBDA_SECRET_FIELDS
            if not getattr(self, field_name)
        ]
        if missing:
            joined = ", ".join(sorted(missing))
            raise ValueError(
                "Missing required runtime settings for Lambda runtime: "
                f"{joined}. Inject them through Infisical/env or configure "
                "BRIEFED_SSM_PREFIX so the Lambda can hydrate them from SSM.",
            )
        return self


def _is_lambda_runtime(env: Mapping[str, str]) -> bool:
    """Return whether ``env`` selects a Lambda runtime.

    Args:
        env: Current process environment.

    Returns:
        ``True`` when ``BRIEFED_RUNTIME`` starts with ``lambda-``.
    """
    return env.get("BRIEFED_RUNTIME", "").startswith("lambda-")


def _is_usable_env_value(value: str | None) -> bool:
    """Return whether an env value should override SSM.

    Args:
        value: Environment variable value.

    Returns:
        ``True`` when ``value`` is non-empty and not a placeholder.
    """
    if value is None:
        return False
    stripped = value.strip()
    return bool(stripped) and not stripped.startswith(_PLACEHOLDER_PREFIX)


def _required_fields_missing_from_env(env: Mapping[str, str]) -> tuple[str, ...]:
    """Return required settings fields not already present in env.

    Args:
        env: Current process environment.

    Returns:
        Tuple of settings field names that need SSM hydration.
    """
    missing: list[str] = []
    for field_name in _REQUIRED_LAMBDA_SECRET_FIELDS:
        field_env_name = field_name.upper()
        values = (
            env.get(f"BRIEFED_{field_env_name}"),
            env.get(field_env_name),
        )
        if not any(_is_usable_env_value(value) for value in values):
            missing.append(field_name)
    return tuple(missing)


def _settings_with_ssm(env: Mapping[str, str]) -> Settings:
    """Load Lambda settings, hydrating missing secrets from SSM when configured.

    Args:
        env: Current process environment.

    Returns:
        Populated settings model.
    """
    prefix = env.get("BRIEFED_SSM_PREFIX")
    if not _is_lambda_runtime(env) or not prefix:
        return Settings()

    missing_fields = _required_fields_missing_from_env(env)
    required_ssm = tuple(_SSM_PARAMETER_BY_FIELD[field] for field in missing_fields)
    optional_ssm = tuple(_OPTIONAL_SSM_PARAMETER_BY_FIELD.values())
    ssm_values = fetch_parameters(
        prefix=prefix,
        required=required_ssm,
        optional=optional_ssm,
    )
    field_values = merge_with_env(
        env=env,
        ssm_values=ssm_values,
        field_to_ssm={**_SSM_PARAMETER_BY_FIELD, **_OPTIONAL_SSM_PARAMETER_BY_FIELD},
    )
    return _settings_from_values(field_values)


def _settings_from_values(values: Mapping[str, str]) -> Settings:
    """Instantiate settings with dynamic keyword values.

    Args:
        values: Field-name keyed values that should override BaseSettings env
            resolution.

    Returns:
        Settings instance with env still used for unspecified fields.
    """
    settings_factory = cast("Callable[..., Settings]", Settings)
    return settings_factory(**values)


def load_settings() -> Settings:
    """Load :class:`Settings` from env, optionally hydrating Lambda SSM secrets.

    This is the **single public entrypoint** for config. Both the FastAPI
    factory and the Lambda handlers call it at module-import time so a
    deployment snapshots a warm, secret-populated process.

    Returns:
        A populated :class:`Settings` instance.
    """
    return _settings_with_ssm(os.environ)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor for application settings.

    Use this in request handlers / dependency injection; the cache
    survives for the life of the process, matching the Lambda warm
    window.

    Returns:
        A shared :class:`Settings` instance.
    """
    return load_settings()
