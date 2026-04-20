"""Unit tests for the LLMClient (plan §20.1 100%-coverage module)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.llm.client import (
    CircuitBreaker,
    LLMClient,
    LLMClientConfig,
    LLMClientError,
    PromptCallRecord,
    RateCap,
    render_prompt,
)
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    reason: str


def _spec() -> PromptSpec:
    return PromptSpec(
        name="triage",
        version=1,
        content="hi {{who}}",
        model="fake-model",
        temperature=0.0,
        max_tokens=100,
        schema_ref="TriageDecision",
    )


class _FakeProvider:
    def __init__(
        self,
        *,
        name: str,
        responses: list[Any],
    ) -> None:
        self.name = name
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        self.calls.append(rendered_prompt)
        if not self._responses:
            raise LLMProviderError("exhausted", retryable=False)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _result(payload: dict[str, Any]) -> LLMCallResult:
    return LLMCallResult(
        payload=payload,
        tokens_in=10,
        tokens_out=5,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost_usd=Decimal("0.000100"),
        latency_ms=42,
        provider="fake",
        model="fake-model",
    )


async def test_primary_success_logs_ok() -> None:
    primary = _FakeProvider(
        name="gemini",
        responses=[_result({"ok": True, "reason": "r"})],
    )
    client = LLMClient(primary=primary)
    logs: list[PromptCallRecord] = []

    async def log(record: PromptCallRecord) -> None:
        logs.append(record)

    response = await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
        log_call=log,
    )
    assert response.fallback_used is False
    assert logs[0].status == "ok"
    assert logs[0].provider == "fake"


async def test_retries_then_succeeds_on_primary() -> None:
    primary = _FakeProvider(
        name="gemini",
        responses=[
            LLMProviderError("flaky", retryable=True),
            _result({"ok": True, "reason": "r"}),
        ],
    )
    client = LLMClient(
        primary=primary,
        config=LLMClientConfig(max_retries=2, base_backoff_seconds=0.0),
    )
    response = await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert response.fallback_used is False
    assert len(primary.calls) == 2


async def test_falls_back_when_primary_fails() -> None:
    primary = _FakeProvider(
        name="gemini",
        responses=[LLMProviderError("hard down", retryable=False)],
    )
    fallback = _FakeProvider(
        name="anthropic_direct",
        responses=[_result({"ok": True, "reason": "r"})],
    )
    client = LLMClient(primary=primary, fallbacks=(fallback,))
    logs: list[PromptCallRecord] = []

    async def log(record: PromptCallRecord) -> None:
        logs.append(record)

    response = await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
        log_call=log,
    )
    assert response.fallback_used is True
    assert logs[0].status == "fallback"


async def test_circuit_opens_after_threshold() -> None:
    primary = _FakeProvider(
        name="gemini",
        responses=[LLMProviderError("boom", retryable=False) for _ in range(10)],
    )
    fallback = _FakeProvider(
        name="anthropic_direct",
        responses=[_result({"ok": True, "reason": "r"}) for _ in range(10)],
    )
    breakers = {"gemini": CircuitBreaker(fail_threshold=2, cool_down_seconds=60)}
    client = LLMClient(primary=primary, fallbacks=(fallback,), breakers=breakers)

    # Trip the breaker in two calls.
    for _ in range(2):
        await client.call(
            spec=_spec(),
            rendered_prompt="hi",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
        )
    assert breakers["gemini"].opened_at is not None

    # Next call skips Gemini without even asking the provider.
    calls_before = len(primary.calls)
    await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert len(primary.calls) == calls_before


async def test_rate_cap_exhausts() -> None:
    primary = _FakeProvider(
        name="gemini",
        responses=[_result({"ok": True, "reason": "r"}) for _ in range(5)],
    )
    fallback = _FakeProvider(
        name="anthropic_direct",
        responses=[_result({"ok": True, "reason": "fb"}) for _ in range(5)],
    )
    cap = RateCap(max_calls=1)
    client = LLMClient(
        primary=primary,
        fallbacks=(fallback,),
        rate_caps={"gemini": cap},
    )
    await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    response = await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert response.call_result.provider == "fake"  # fallback _FakeProvider
    assert response.fallback_used is True


async def test_schema_mismatch_bubbles_to_next_provider() -> None:
    primary = _FakeProvider(
        name="gemini",
        responses=[_result({"ok": "not-a-bool", "reason": "x"})],
    )
    fallback = _FakeProvider(
        name="anthropic_direct",
        responses=[_result({"ok": True, "reason": "ok"})],
    )
    client = LLMClient(primary=primary, fallbacks=(fallback,))
    response = await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert response.fallback_used is True


async def test_all_providers_fail_raises_and_logs_error() -> None:
    primary = _FakeProvider(
        name="gemini",
        responses=[LLMProviderError("x", retryable=False)],
    )
    fallback = _FakeProvider(
        name="anthropic_direct",
        responses=[LLMProviderError("y", retryable=False)],
    )
    client = LLMClient(primary=primary, fallbacks=(fallback,))
    logs: list[PromptCallRecord] = []

    async def log(record: PromptCallRecord) -> None:
        logs.append(record)

    with pytest.raises(LLMClientError):
        await client.call(
            spec=_spec(),
            rendered_prompt="hi",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
            log_call=log,
        )
    assert logs and logs[-1].status == "error"


def test_render_prompt_interpolates() -> None:
    spec = _spec()
    rendered = render_prompt(spec, {"who": "world"})
    assert rendered == "hi world"


def test_render_prompt_missing_variable_raises() -> None:
    spec = _spec()
    with pytest.raises(KeyError):
        render_prompt(spec, {})


def test_circuit_breaker_resets_on_success() -> None:
    breaker = CircuitBreaker(fail_threshold=3)
    breaker.record_failure()
    breaker.record_success()
    assert breaker.consecutive_failures == 0
    assert breaker.opened_at is None
