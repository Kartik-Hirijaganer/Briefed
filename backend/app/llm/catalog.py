"""OpenRouter model catalog loaded from ``packages/config/llm/catalog.yml``.

The module preserves the existing public API:

* :data:`CATALOG`
* :data:`PRIMARY`
* :data:`FALLBACKS`
* :func:`resolve`
* :func:`chain`

The backing YAML is parsed into a frozen Pydantic :class:`ModelCatalog`
at import time. Missing or malformed catalog data raises immediately
because routing a prompt to the wrong model must never be silent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self, overload

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.yaml import YamlConfigError, safe_load_yaml_file

ModelEntryKey = Literal[
    "openrouter_id",
    "cost_per_m_input_usd",
    "cost_per_m_output_usd",
    "daily_call_cap",
    "max_output_tokens",
]
"""Subscript keys supported by :class:`ModelEntry` for API compatibility."""


class CatalogConfigError(ValueError):
    """Raised when the model catalog file is missing or invalid."""


class ModelEntry(BaseModel):
    """One OpenRouter catalog row.

    Attributes:
        openrouter_id: Route identifier OpenRouter expects in the
            ``model`` request field.
        cost_per_m_input_usd: Advisory input-token price in USD per
            million tokens.
        cost_per_m_output_usd: Advisory output-token price in USD per
            million tokens.
        daily_call_cap: Optional per-process daily call cap.
        max_output_tokens: Hard upper bound passed to OpenRouter.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    openrouter_id: str = Field(..., min_length=1, description="OpenRouter route id.")
    cost_per_m_input_usd: float = Field(
        ...,
        ge=0.0,
        description="Fallback input-token cost in USD per million tokens.",
    )
    cost_per_m_output_usd: float = Field(
        ...,
        ge=0.0,
        description="Fallback output-token cost in USD per million tokens.",
    )
    daily_call_cap: int | None = Field(
        default=None,
        ge=1,
        description="Optional per-day call cap for this catalog key.",
    )
    max_output_tokens: int = Field(..., ge=1, description="Maximum output tokens.")

    @overload
    def __getitem__(self, key: Literal["openrouter_id"]) -> str: ...

    @overload
    def __getitem__(self, key: Literal["cost_per_m_input_usd"]) -> float: ...

    @overload
    def __getitem__(self, key: Literal["cost_per_m_output_usd"]) -> float: ...

    @overload
    def __getitem__(self, key: Literal["daily_call_cap"]) -> int | None: ...

    @overload
    def __getitem__(self, key: Literal["max_output_tokens"]) -> int: ...

    def __getitem__(self, key: ModelEntryKey) -> str | float | int | None:
        """Return a field value using the legacy mapping-style API.

        Args:
            key: Catalog row field name.

        Returns:
            Matching field value.
        """
        if key == "openrouter_id":
            return self.openrouter_id
        if key == "cost_per_m_input_usd":
            return self.cost_per_m_input_usd
        if key == "cost_per_m_output_usd":
            return self.cost_per_m_output_usd
        if key == "daily_call_cap":
            return self.daily_call_cap
        return self.max_output_tokens


class ModelCatalog(BaseModel):
    """Validated model catalog.

    Attributes:
        models: Friendly-name mapping to OpenRouter model entries.
        primary: Friendly-name for the default primary model.
        fallbacks: Ordered fallback friendly names.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    models: dict[str, ModelEntry] = Field(..., min_length=1, description="Model entries.")
    primary: str = Field(..., min_length=1, description="Primary model key.")
    fallbacks: tuple[str, ...] = Field(default=(), description="Fallback model keys.")

    @model_validator(mode="after")
    def _validate_chain(self) -> Self:
        """Validate that every chain key exists in ``models``.

        Returns:
            The validated catalog.

        Raises:
            ValueError: If the primary or a fallback key is unknown.
        """
        if self.primary not in self.models:
            raise ValueError(f"primary model {self.primary!r} is not in models")
        missing_fallbacks = [name for name in self.fallbacks if name not in self.models]
        if missing_fallbacks:
            raise ValueError(f"fallback models not in models: {missing_fallbacks!r}")
        return self


class UnknownModelError(KeyError):
    """Raised when :func:`resolve` is asked for a model not in the catalog."""


def default_model_catalog_path() -> Path:
    """Return the packaged or repo-relative model catalog path.

    Returns:
        Absolute path to ``packages/config/llm/catalog.yml``.
    """
    import os  # noqa: PLC0415 - Lambda task root is only needed while resolving paths.

    raw_task_root = os.environ.get("LAMBDA_TASK_ROOT")
    if raw_task_root:
        lambda_path = Path(raw_task_root) / "packages" / "config" / "llm" / "catalog.yml"
        if lambda_path.exists():
            return lambda_path
    return Path(__file__).resolve().parents[3] / "packages" / "config" / "llm" / "catalog.yml"


def load_model_catalog(path: Path | None = None) -> ModelCatalog:
    """Load and validate the model catalog from YAML.

    Args:
        path: Optional path override, mainly for tests.

    Returns:
        Parsed :class:`ModelCatalog`.

    Raises:
        CatalogConfigError: If the file is missing, malformed, or violates
            catalog invariants.
    """
    config_path = path if path is not None else default_model_catalog_path()
    try:
        payload = safe_load_yaml_file(config_path)
        return ModelCatalog.model_validate(payload)
    except (YamlConfigError, ValidationError) as exc:
        raise CatalogConfigError(f"invalid model catalog at {config_path}") from exc


_MODEL_CATALOG = load_model_catalog()
"""Validated catalog snapshot loaded at import time."""

CATALOG: dict[str, ModelEntry] = dict(_MODEL_CATALOG.models)
"""Friendly-name to :class:`ModelEntry`. Single source of truth."""

PRIMARY: str = _MODEL_CATALOG.primary
"""Friendly-name of the primary route used by the default chain."""

FALLBACKS: list[str] = list(_MODEL_CATALOG.fallbacks)
"""Ordered fallback chain after :data:`PRIMARY`."""


def resolve(name: str) -> ModelEntry:
    """Return the :class:`ModelEntry` for ``name``.

    Args:
        name: Friendly-name key.

    Returns:
        The matching :class:`ModelEntry`.

    Raises:
        UnknownModelError: When ``name`` is not in :data:`CATALOG`.
    """
    try:
        return CATALOG[name]
    except KeyError as exc:
        raise UnknownModelError(name) from exc


def chain() -> list[str]:
    """Return the default catalog-driven chain ``[PRIMARY, *FALLBACKS]``."""
    return [PRIMARY, *FALLBACKS]


__all__ = [
    "CATALOG",
    "FALLBACKS",
    "PRIMARY",
    "CatalogConfigError",
    "ModelCatalog",
    "ModelEntry",
    "UnknownModelError",
    "chain",
    "default_model_catalog_path",
    "load_model_catalog",
    "resolve",
]
