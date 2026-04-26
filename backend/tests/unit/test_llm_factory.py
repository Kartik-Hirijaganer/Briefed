"""Unit tests for :func:`app.llm.factory.build_llm_client` (ADR 0009).

The factory wires the :class:`OpenRouterProvider` chain into
:class:`LLMClient`. The legacy Gemini/Anthropic branch was deleted at
T+30 days post-cutover.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.llm import catalog
from app.llm.factory import build_llm_client
from app.llm.providers import OpenRouterProvider


def _settings(monkeypatch: pytest.MonkeyPatch, **env_overrides: str | None) -> Settings:
    """Build a Settings instance with predictable env."""
    base: dict[str, str | None] = {
        "BRIEFED_RUNTIME": "local",
        "BRIEFED_ENV": "local",
        "OPENROUTER_API_KEY": "or-key",
        "BRIEFED_DAILY_LLM_USD_CAP": None,
        "BRIEFED_SSM_PREFIX": None,
    }
    base.update(env_overrides)
    for key, value in base.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return Settings()


async def test_factory_builds_catalog_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch)
    async with httpx.AsyncClient() as http:
        client = build_llm_client(settings=settings, http_client=http)

    assert isinstance(client.primary, OpenRouterProvider)
    assert client.primary.name == f"openrouter:{catalog.PRIMARY}"
    expected_fallbacks = [f"openrouter:{n}" for n in catalog.FALLBACKS]
    assert [p.name for p in client.fallbacks] == expected_fallbacks


async def test_factory_requires_openrouter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch, OPENROUTER_API_KEY=None)
    async with httpx.AsyncClient() as http:
        with pytest.raises(ValueError, match="openrouter_api_key"):
            build_llm_client(settings=settings, http_client=http)


async def test_daily_cap_threads_through_to_budget_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch, BRIEFED_DAILY_LLM_USD_CAP="0.5")
    async with httpx.AsyncClient() as http:
        client = build_llm_client(settings=settings, http_client=http)

    assert client._budget_guard is not None
    assert client._budget_guard.daily_cap_usd == 0.5


async def test_no_cap_means_no_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch, BRIEFED_DAILY_LLM_USD_CAP=None)
    async with httpx.AsyncClient() as http:
        client = build_llm_client(settings=settings, http_client=http)
    assert client._budget_guard is None


async def test_openrouter_chain_carries_per_model_rate_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catalog ``daily_call_cap`` rolls up to RateCaps keyed by friendly name."""
    settings = _settings(monkeypatch)
    async with httpx.AsyncClient() as http:
        client = build_llm_client(settings=settings, http_client=http)
    expected_key = "openrouter:claude-haiku"
    assert expected_key in client._rate_caps
    assert client._rate_caps[expected_key].max_calls == 100
