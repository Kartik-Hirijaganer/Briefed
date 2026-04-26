"""Unit tests for :class:`OpenRouterProvider` (Track A Phase 3).

Tests use :mod:`respx` to stub OpenRouter and cover success, JSON-mode
request shape, retryable 5xx, non-retryable 4xx, ``usage.cost`` parsing,
and the local-estimate fallback when ``cost`` is absent.
"""

from __future__ import annotations

import os
from decimal import Decimal

import httpx
import pytest
import respx

from app.llm.catalog import resolve
from app.llm.providers.base import LLMProviderError, PromptSpec
from app.llm.providers.openrouter import OpenRouterProvider

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def _spec(*, schema: str = "TriageDecision") -> PromptSpec:
    return PromptSpec(
        name="triage",
        version=1,
        content="hi {{who}}",
        model="gemini-flash",
        temperature=0.0,
        max_tokens=200,
        schema_ref=schema,
    )


@respx.mock
async def test_success_with_json_mode_and_usage_cost() -> None:
    route = respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ok": true, "reason": "yes"}'}},
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "cost": 0.000123,
                },
            },
        )
    )
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        result = await provider.complete_json(_spec(), rendered_prompt="hi world")

    assert route.called
    sent = route.calls.last.request
    body = sent.read()
    assert b'"data_collection":"deny"' in body
    assert b'"transforms":[]' in body
    assert b'"response_format":{"type":"json_object"}' in body
    assert sent.headers["X-Title"] == "Briefed"
    assert "HTTP-Referer" not in sent.headers
    assert sent.headers["Authorization"] == "Bearer k"

    assert result.payload == {"ok": True, "reason": "yes"}
    assert result.tokens_in == 10
    assert result.tokens_out == 4
    assert result.cost_usd == Decimal("0.000123")
    assert result.provider == "openrouter"
    assert result.model == "google/gemini-2.0-flash-001"


@respx.mock
async def test_skips_response_format_when_no_schema() -> None:
    route = respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true, "reason": "x"}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0},
            },
        )
    )
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        await provider.complete_json(_spec(schema=""), rendered_prompt="hi")

    body = route.calls.last.request.read()
    assert b"response_format" not in body


@respx.mock
async def test_retryable_on_5xx() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(503, text="overloaded"))
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        with pytest.raises(LLMProviderError) as exc:
            await provider.complete_json(_spec(), rendered_prompt="hi")
    assert exc.value.retryable is True


@respx.mock
async def test_retryable_on_429() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(429, text="rate"))
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        with pytest.raises(LLMProviderError) as exc:
            await provider.complete_json(_spec(), rendered_prompt="hi")
    assert exc.value.retryable is True


@respx.mock
async def test_non_retryable_on_4xx() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(401, text="bad key"))
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        with pytest.raises(LLMProviderError) as exc:
            await provider.complete_json(_spec(), rendered_prompt="hi")
    assert exc.value.retryable is False


@respx.mock
async def test_local_estimate_used_when_cost_missing() -> None:
    respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ok": true, "reason": "x"}'}},
                ],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
            },
        )
    )
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        result = await provider.complete_json(_spec(), rendered_prompt="hi")
    # gemini-flash pricing: 0.10 + 0.40 = 0.50 per million in + million out.
    assert result.cost_usd == Decimal("0.500000")


@respx.mock
async def test_malformed_cost_falls_back_to_estimate() -> None:
    respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true, "reason": "x"}'}}],
                "usage": {
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 0,
                    "cost": "not-a-number",
                },
            },
        )
    )
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        result = await provider.complete_json(_spec(), rendered_prompt="hi")
    assert result.cost_usd == Decimal("0.100000")


@respx.mock
async def test_empty_choices_raises() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json={"choices": [], "usage": {}}))
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        with pytest.raises(LLMProviderError):
            await provider.complete_json(_spec(), rendered_prompt="hi")


@respx.mock
async def test_non_json_body_raises_non_retryable() -> None:
    respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "this is not json"}}],
                "usage": {},
            },
        )
    )
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        with pytest.raises(LLMProviderError) as exc:
            await provider.complete_json(_spec(), rendered_prompt="hi")
    assert exc.value.retryable is False


@respx.mock
async def test_strips_markdown_fences() -> None:
    respx.post(_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '```json\n{"ok": true, "reason": "y"}\n```'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0},
            },
        )
    )
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        result = await provider.complete_json(_spec(), rendered_prompt="hi")
    assert result.payload == {"ok": True, "reason": "y"}


@respx.mock
async def test_transport_error_is_retryable() -> None:
    respx.post(_ENDPOINT).mock(side_effect=httpx.ConnectError("nope"))
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key="k",
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        with pytest.raises(LLMProviderError) as exc:
            await provider.complete_json(_spec(), rendered_prompt="hi")
    assert exc.value.retryable is True


def test_empty_api_key_rejected() -> None:
    with pytest.raises(LLMProviderError):
        OpenRouterProvider(
            api_key="",
            http_client=httpx.AsyncClient(),
            catalog_entry=resolve("gemini-flash"),
        )


@pytest.mark.skipif(
    os.environ.get("OPENROUTER_LIVE") != "1",
    reason="OPENROUTER_LIVE=1 not set — opt-in live smoke test",
)
async def test_live_smoke_round_trip() -> None:  # pragma: no cover — opt-in
    """Plan Phase 3 — opt-in live smoke test."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    assert api_key, "OPENROUTER_API_KEY required when OPENROUTER_LIVE=1"
    async with httpx.AsyncClient() as http:
        provider = OpenRouterProvider(
            api_key=api_key,
            http_client=http,
            catalog_entry=resolve("gemini-flash"),
        )
        result = await provider.complete_json(
            _spec(),
            rendered_prompt='Reply with JSON {"ok": true, "reason": "smoke"}',
        )
    assert result.payload.get("ok") is True
