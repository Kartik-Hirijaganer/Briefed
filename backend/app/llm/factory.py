"""Factory that builds an :class:`LLMClient` for the OpenRouter chain.

ADR 0009 — OpenRouter is the sole direct LLM provider. The legacy
Gemini + Anthropic direct adapters were deleted at T+30 days
post-cutover; their git history is the rollback path.

The fallback chain order is catalog-driven
(``[CATALOG primary, *CATALOG fallbacks]``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.llm import catalog
from app.llm.client import LLMBudgetGuard, LLMClient, RateCap
from app.llm.providers import LLMProvider, OpenRouterProvider

if TYPE_CHECKING:  # pragma: no cover
    import httpx

    from app.core.config import Settings
    from app.llm.redaction.types import Sanitizer


def build_llm_client(
    *,
    settings: Settings,
    http_client: httpx.AsyncClient,
    sanitizer: Sanitizer | None = None,
) -> LLMClient:
    """Construct an :class:`LLMClient` configured for ``settings``.

    Args:
        settings: Active application settings. ``daily_llm_usd_cap``
            (when set) enables the global cost guard.
        http_client: Shared :class:`httpx.AsyncClient`. Caller owns
            its lifecycle (typically a worker handler ``async with``
            block).
        sanitizer: Optional :class:`Sanitizer` (Track B redaction
            layer) plumbed straight into the returned client.

    Returns:
        A wired :class:`LLMClient`.

    Raises:
        ValueError: When ``openrouter_api_key`` is unset.
    """
    primary, fallbacks, rate_caps = _build_openrouter_chain(
        api_key=settings.openrouter_api_key or "",
        http_client=http_client,
    )

    budget_guard: LLMBudgetGuard | None = (
        LLMBudgetGuard(daily_cap_usd=settings.daily_llm_usd_cap)
        if settings.daily_llm_usd_cap is not None
        else None
    )

    return LLMClient(
        primary=primary,
        fallbacks=fallbacks,
        rate_caps=rate_caps,
        budget_guard=budget_guard,
        sanitizer=sanitizer,
    )


def _build_openrouter_chain(
    *,
    api_key: str,
    http_client: httpx.AsyncClient,
) -> tuple[LLMProvider, tuple[LLMProvider, ...], dict[str, RateCap]]:
    """Build the OpenRouter chain ``[CATALOG primary, *CATALOG fallbacks]``."""
    if not api_key:
        raise ValueError(
            "openrouter backend selected but openrouter_api_key is unset",
        )

    chain_names = catalog.chain()
    chain: list[LLMProvider] = []
    rate_caps: dict[str, RateCap] = {}
    for name in chain_names:
        entry = catalog.resolve(name)
        provider = OpenRouterProvider(
            api_key=api_key,
            http_client=http_client,
            catalog_entry=entry,
        )
        # Per-model breakers + caps are keyed by friendly name so the
        # CloudWatch alarm names line up with the catalog rather than
        # the shared ``openrouter`` provider slug.
        provider.name = f"openrouter:{name}"
        chain.append(provider)
        cap = entry["daily_call_cap"]
        if cap is not None:
            rate_caps[provider.name] = RateCap(max_calls=cap)

    primary = chain[0]
    fallbacks = tuple(chain[1:])
    return primary, fallbacks, rate_caps


__all__ = ["build_llm_client"]
