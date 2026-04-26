"""Chaos drill — Gemini rate-limit + Anthropic fallback (plan §19.15 Phase 8).

The exit criterion is "Gemini rate-limit + fallback chaos test." We
simulate Gemini returning a retryable rate-limit error on every attempt
(``LLMProviderError(retryable=True)``) and assert the LLM client falls
through to the Anthropic Haiku fallback. The fallback rate-cap must
remain enforced (plan §19.15 hard cap of 100 calls/day).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict

from app.llm.client import LLMClient, LLMClientConfig, RateCap
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec

pytestmark = pytest.mark.chaos


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    reason: str


def _spec() -> PromptSpec:
    return PromptSpec(
        name="triage",
        version=1,
        content="hi",
        model="fake-model",
        temperature=0.0,
        max_tokens=64,
        schema_ref="TriageDecision",
    )


def _success() -> LLMCallResult:
    return LLMCallResult(
        payload={"ok": True, "reason": "fallback served"},
        tokens_in=1,
        tokens_out=1,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost_usd=Decimal("0.000050"),
        latency_ms=12,
        provider="anthropic_direct",
        model="claude-haiku-4-5",
    )


class _RateLimited:
    name = "gemini"
    calls = 0

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        self.calls += 1
        raise LLMProviderError("rate limit", retryable=True)


class _Fallback:
    name = "anthropic_direct"
    calls = 0

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        self.calls += 1
        return _success()


async def test_gemini_rate_limit_falls_back_to_anthropic() -> None:
    primary = _RateLimited()
    fallback = _Fallback()
    client = LLMClient(
        primary=primary,
        fallbacks=(fallback,),
        config=LLMClientConfig(max_retries=1, base_backoff_seconds=0.0),
        rate_caps={"anthropic_direct": RateCap(max_calls=100)},
    )
    response = await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert response.fallback_used is True
    assert fallback.calls == 1


async def test_anthropic_fallback_cap_is_enforced() -> None:
    """The Haiku fallback hard cap of 100 calls/day still applies (§19.15)."""
    primary = _RateLimited()
    fallback = _Fallback()
    cap = RateCap(max_calls=2)
    client = LLMClient(
        primary=primary,
        fallbacks=(fallback,),
        config=LLMClientConfig(max_retries=1, base_backoff_seconds=0.0),
        rate_caps={"anthropic_direct": cap},
    )
    for _ in range(2):
        await client.call(
            spec=_spec(),
            rendered_prompt="hi",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
        )
    # Third call exhausts the cap; the client must fail loudly rather
    # than smuggling another fallback request through.
    with pytest.raises(Exception):
        await client.call(
            spec=_spec(),
            rendered_prompt="hi",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
        )
    assert fallback.calls == 2
