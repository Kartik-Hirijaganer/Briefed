"""OpenRouter model catalog (ADR 0009 / Track A Phase 2).

A single typed dict that maps friendly names (``gemini-flash``,
``claude-haiku``) to the OpenRouter route identifier and per-call
billing / safety tunables.

Adding a future model is a one-line edit — append an entry to
:data:`CATALOG` and reference it from :data:`PRIMARY` /
:data:`FALLBACKS` if it should join the default chain.

The plan rejected a YAML catalog and Pydantic-validated import: this is
a single-user project, the catalog has two entries, and Python types +
``mypy --strict`` give us the same guarantees with no extra format.

Pricing values mirror the OpenRouter price table observed during the
Phase 0 spike. They are advisory only — :class:`OpenRouterProvider`
records the per-call ``usage.cost`` field (when present) as the
authoritative cost figure. The static prices give us a fallback when a
provider route returns the call without `cost` (unusual but possible).
"""

from __future__ import annotations

from typing import TypedDict


class ModelEntry(TypedDict):
    """One catalog row.

    Attributes:
        openrouter_id: Route identifier OpenRouter expects in the
            ``model`` request field (e.g. ``google/gemini-2.0-flash-001``).
        cost_per_m_input_usd: Advisory input-token price ($/M) used as
            the local estimate when ``usage.cost`` is missing.
        cost_per_m_output_usd: Advisory output-token price ($/M).
        daily_call_cap: Optional per-process daily call cap, mirrors
            :class:`app.llm.client.RateCap`. ``None`` disables.
        max_output_tokens: Hard upper bound on ``max_tokens`` for this
            route — passed straight through to the OpenRouter request.
    """

    openrouter_id: str
    cost_per_m_input_usd: float
    cost_per_m_output_usd: float
    daily_call_cap: int | None
    max_output_tokens: int


CATALOG: dict[str, ModelEntry] = {
    "gemini-flash": {
        "openrouter_id": "google/gemini-2.0-flash-001",
        "cost_per_m_input_usd": 0.10,
        "cost_per_m_output_usd": 0.40,
        "daily_call_cap": None,
        "max_output_tokens": 8192,
    },
    "claude-haiku": {
        "openrouter_id": "anthropic/claude-haiku-4.5",
        "cost_per_m_input_usd": 1.00,
        "cost_per_m_output_usd": 5.00,
        "daily_call_cap": 100,
        "max_output_tokens": 8192,
    },
}
"""Friendly-name → :class:`ModelEntry`. Single source of truth."""


PRIMARY: str = "gemini-flash"
"""Friendly-name of the primary route used by the default chain."""


FALLBACKS: list[str] = ["claude-haiku"]
"""Ordered fallback chain (after :data:`PRIMARY`)."""


class UnknownModelError(KeyError):
    """Raised when :func:`resolve` is asked for a model not in the catalog."""


def resolve(name: str) -> ModelEntry:
    """Return the :class:`ModelEntry` for ``name``.

    Args:
        name: Friendly-name key (``gemini-flash`` etc.).

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
    "ModelEntry",
    "UnknownModelError",
    "chain",
    "resolve",
]
