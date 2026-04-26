"""Typed application settings, with SSM Parameter Store hydration.

Two modes coexist:

* **Local / test** — ``BRIEFED_RUNTIME=local`` (the default). Values are
  read from process env + an optional ``.env`` file via
  :mod:`pydantic_settings`; missing non-required secrets fall back to
  ``None`` so ``pytest`` does not require live credentials.

* **Lambda** — ``BRIEFED_RUNTIME`` starts with ``lambda-`` and
  ``briefed_ssm_prefix`` is set. Secrets are pulled from SSM at cold-start
  and merged in. A missing required parameter raises
  :class:`~app.integrations.ssm_secrets.MissingSecretError` immediately —
  Lambda init fails, CloudWatch surfaces the error, and SnapStart does
  not snapshot a broken process.

The Phase 0 exit-criteria unit test
(:mod:`backend.tests.unit.test_config`) exercises the second path via
an injected fake SSM client.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.integrations.ssm_secrets import fetch_parameters, merge_with_env

Runtime = Literal["local", "lambda-api", "lambda-worker", "lambda-fanout"]
"""The deployment shape the current process is serving."""


# Maps Settings field-name → SSM parameter short-name. The short-name is
# appended to ``briefed_ssm_prefix`` to form the full SSM path (e.g.
# ``/briefed/dev/openrouter_api_key``). Field names align with the SSM
# names declared by :mod:`infra/terraform/modules/ssm/main.tf`.
_SSM_FIELD_MAP: dict[str, str] = {
    "openrouter_api_key": "openrouter_api_key",
    "google_oauth_client_id": "google_oauth_client_id",
    "google_oauth_client_secret": "google_oauth_client_secret",
    "session_signing_key": "session_signing_key",
    "supabase_url": "supabase_url",
    "supabase_service_key": "supabase_service_key",
    "database_url": "supabase_db_url",
}

# Subset of ``_SSM_FIELD_MAP`` that must be present before the app can
# serve any real request. Values absent from the Lambda environment AND
# from SSM cause a hard fail at init.
_REQUIRED_SECRETS: tuple[str, ...] = (
    "openrouter_api_key",
    "session_signing_key",
    "google_oauth_client_id",
    "google_oauth_client_secret",
    "database_url",
)


class Settings(BaseSettings):
    """Typed application settings.

    Attributes cover three buckets: runtime identity (``env`` /
    ``runtime``), operator-tunable knobs (``log_level``,
    ``ssm_prefix``), and secrets hydrated from SSM / env.

    Uses ``model_config = SettingsConfigDict(env_file=".env", extra="ignore")``
    so local ``.env`` overrides work out of the box; unknown env vars are
    ignored (boto3 + LocalStack set several).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = Field(default="local", description="Environment slug (local/dev/prod).")
    runtime: Runtime = Field(
        default="local",
        description="Which deployment surface this process is serving.",
        validation_alias="BRIEFED_RUNTIME",
    )
    log_level: str = Field(default="info", description="Minimum log level name.")

    ssm_prefix: str | None = Field(
        default=None,
        description="SSM parameter prefix for secret hydration (e.g. '/briefed/dev/').",
        validation_alias="BRIEFED_SSM_PREFIX",
    )

    database_url: str | None = Field(
        default=None,
        description="SQLAlchemy async URL (asyncpg driver).",
        validation_alias="BRIEFED_DATABASE_URL",
    )

    # Secrets (nullable so local / CI startup is possible without them).
    openrouter_api_key: str | None = Field(
        default=None,
        description="OpenRouter API key — required in Lambda runtimes (ADR 0009).",
    )
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    session_signing_key: str | None = None
    supabase_url: str | None = None
    supabase_service_key: str | None = None

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

    # Track B / ADR 0010 — LLM prompt redaction.
    redaction_presidio_enabled: bool = Field(
        default=True,
        description=(
            "Enable the Presidio sanitizer in the redaction chain. "
            "Flip to False if Phase 6 quality eval shows regression."
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


def _hydrate_from_ssm(
    settings: Settings,
    *,
    ssm_client: object | None = None,
    env: dict[str, str] | None = None,
) -> Settings:
    """Pull required + optional secrets from SSM and return a new Settings.

    Only invoked when ``settings.runtime`` is a Lambda flavor and
    ``settings.ssm_prefix`` is set. Delegates to
    :func:`app.integrations.ssm_secrets.fetch_parameters` which raises
    :class:`~app.integrations.ssm_secrets.MissingSecretError` when any
    required parameter is absent.

    Args:
        settings: Initial Settings from env + ``.env``.
        ssm_client: Optional SSM client (injected from tests).
        env: Environment mapping; defaults to ``os.environ``.

    Returns:
        A new :class:`Settings` with SSM-sourced values merged in. Env
        vars still win over SSM when both are set (local overrides).
    """
    import os  # noqa: PLC0415 — lazy to keep module import cheap

    prefix = settings.ssm_prefix
    if prefix is None:  # pragma: no cover — guarded by the caller
        raise RuntimeError("_hydrate_from_ssm invoked without ssm_prefix")

    ssm_values = fetch_parameters(
        prefix=prefix,
        required=tuple(_SSM_FIELD_MAP[f] for f in _REQUIRED_SECRETS),
        optional=tuple(_SSM_FIELD_MAP[f] for f in _SSM_FIELD_MAP if f not in _REQUIRED_SECRETS),
        client=ssm_client,  # type: ignore[arg-type]
    )

    merged = merge_with_env(
        env=env if env is not None else dict(os.environ),
        ssm_values=ssm_values,
        field_to_ssm=_SSM_FIELD_MAP,
    )

    return settings.model_copy(update=merged)


def load_settings(
    *,
    ssm_client: object | None = None,
    env: dict[str, str] | None = None,
) -> Settings:
    """Load :class:`Settings`, hydrating secrets from SSM when appropriate.

    This is the **single public entrypoint** for config. Both the FastAPI
    factory and the Lambda handlers call it at module-import time so
    SnapStart captures a warm, secret-populated process.

    Args:
        ssm_client: Optional SSM client; pass a mock in tests to avoid
            real AWS calls.
        env: Optional environment mapping; defaults to ``os.environ``.
            Mainly used by tests to inject a specific env without
            polluting the real process environment.

    Returns:
        A populated :class:`Settings`. In Lambda mode, every name in
        ``_REQUIRED_SECRETS`` is guaranteed non-``None``.

    Raises:
        MissingSecretError: In Lambda mode, if any required SSM parameter
            is missing or still holds the Terraform placeholder value.
    """
    settings = Settings()

    if settings.runtime.startswith("lambda-") and settings.ssm_prefix:
        settings = _hydrate_from_ssm(settings, ssm_client=ssm_client, env=env)

    return settings


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
