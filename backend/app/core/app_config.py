"""Typed YAML application config for behavior-neutral product knobs.

``packages/config/app_config.yml`` is the repository-owned source of
non-secret product defaults. Local and test runs fall back to the
Pydantic defaults if the file is absent or malformed; Lambda runtimes
raise during module initialization so SnapStart never snapshots a
silently misconfigured process.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Runtime, get_settings
from app.core.yaml import YamlConfigError, safe_load_yaml_file


class AppConfigError(ValueError):
    """Raised when app YAML config cannot be loaded in a strict runtime."""


class FeatureConfig(BaseModel):
    """Feature toggles that document optional product surfaces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    jobs: bool = Field(default=False, description="Reserved seam for removed job extraction.")
    unsubscribe: bool = Field(default=True, description="Whether unsubscribe suggestions run.")
    unsubscribe_execute: bool = Field(
        default=False,
        description=(
            "Whether the agent may actually execute unsubscribes (ADR 0014). "
            "Default off: the unsubscribe page stays recommend-only until this "
            "is enabled. Single source of truth gating POST "
            "/unsubscribes/{id}/execute and the frontend execute UX."
        ),
    )
    newsletter_clustering: bool = Field(
        default=True,
        description="Whether newsletter clustering and tech-news summaries run.",
    )
    presidio: bool = Field(default=False, description="Presidio was removed; keep false.")


class ClassificationConfig(BaseModel):
    """Classification confidence thresholds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    low_confidence_threshold: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Rule confidence below which the LLM is still consulted.",
    )
    needs_review_threshold: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Model confidence below which the row is flagged for review.",
    )


class ApiConfig(BaseModel):
    """API pagination and recommendation defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dashboard_preview_limit: int = Field(
        default=5,
        ge=1,
        description="Number of must-read preview rows shown on the dashboard.",
    )
    emails_default_limit: int = Field(
        default=50,
        ge=1,
        description="Default page size for classified email lists.",
    )
    emails_max_limit: int = Field(
        default=100,
        ge=1,
        description="Maximum page size accepted by classified email lists.",
    )
    unsubscribe_recommendation_confidence_min: Decimal = Field(
        default=Decimal("0.800"),
        ge=Decimal("0"),
        le=Decimal("1"),
        description="Minimum confidence for visible unsubscribe recommendations.",
    )
    top_domain_cap: int = Field(
        default=10,
        ge=1,
        description="Maximum noisy domains returned by hygiene stats.",
    )


class TaxonomyConfig(BaseModel):
    """Current classification labels grouped by read-model purpose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_facing_buckets: tuple[str, ...] = Field(
        default=("must_read", "good_to_read", "ignore"),
        description="Labels rendered as primary user-facing buckets.",
    )
    summarizable_labels: tuple[str, ...] = Field(
        default=("must_read", "good_to_read"),
        description="Labels that qualify for per-email summaries.",
    )
    newsletter_label: str = Field(
        default="newsletter",
        description="Legacy pseudo-label used by newsletter clustering.",
    )


class ScanConfig(BaseModel):
    """Mailbox scan defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lookback_days: int = Field(
        default=14,
        ge=1,
        description="Bootstrap Gmail messages.list lookback window in days.",
    )
    unread_only: bool = Field(
        default=True,
        description="Whether Gmail bootstrap queries are restricted to unread messages.",
    )


class AppConfig(BaseModel):
    """Repository-owned application config loaded from YAML."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    features: FeatureConfig = Field(default_factory=FeatureConfig, description="Feature flags.")
    classification: ClassificationConfig = Field(
        default_factory=ClassificationConfig,
        description="Classification thresholds.",
    )
    api: ApiConfig = Field(default_factory=ApiConfig, description="API defaults.")
    taxonomy: TaxonomyConfig = Field(default_factory=TaxonomyConfig, description="Taxonomy sets.")
    scan: ScanConfig = Field(default_factory=ScanConfig, description="Mailbox scan defaults.")


def default_app_config_path() -> Path:
    """Return the packaged or repo-relative app config path.

    Returns:
        Absolute path to ``packages/config/app_config.yml``.
    """
    import os  # noqa: PLC0415 - Lambda task root is only needed while resolving paths.

    raw_task_root = os.environ.get("LAMBDA_TASK_ROOT")
    if raw_task_root:
        lambda_path = Path(raw_task_root) / "packages" / "config" / "app_config.yml"
        if lambda_path.exists():
            return lambda_path
    return Path(__file__).resolve().parents[3] / "packages" / "config" / "app_config.yml"


def load_app_config(
    path: Path | None = None,
    *,
    runtime: Runtime | None = None,
) -> AppConfig:
    """Load application config, falling back locally and failing in Lambda.

    Args:
        path: Optional path override, mainly for tests.
        runtime: Optional runtime override. Defaults to ``get_settings().runtime``.

    Returns:
        Parsed and frozen :class:`AppConfig`.

    Raises:
        AppConfigError: In Lambda runtime, when the file is missing,
            malformed, or violates the schema.
    """
    active_runtime = runtime if runtime is not None else get_settings().runtime
    strict = active_runtime.startswith("lambda-")
    config_path = path if path is not None else default_app_config_path()

    try:
        payload = safe_load_yaml_file(config_path)
        return AppConfig.model_validate(payload)
    except (YamlConfigError, ValidationError) as exc:
        if strict:
            raise AppConfigError(f"invalid app config at {config_path}") from exc
        return AppConfig()


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    """Return the memoized application config.

    Returns:
        Shared :class:`AppConfig` for the current process.
    """
    return load_app_config()


__all__ = [
    "ApiConfig",
    "AppConfig",
    "AppConfigError",
    "ClassificationConfig",
    "FeatureConfig",
    "ScanConfig",
    "TaxonomyConfig",
    "default_app_config_path",
    "get_app_config",
    "load_app_config",
]
