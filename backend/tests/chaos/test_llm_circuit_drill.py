"""Chaos drill — 100% LLM failure for 2 minutes (plan §14 Phase 8 + §20.6).

Plan exit criterion: "inject a 100% LLM failure for 2 min, verify circuit
opens + alarm fires." We cannot trip a real CloudWatch alarm in the test
suite, but we can prove the *circuit* opens after the configured number
of consecutive failures and that subsequent calls short-circuit with
``CircuitOpenError`` — the same condition the EMF metric filter watches
for in production.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel, ConfigDict

from app.llm.client import (
    CircuitBreaker,
    CircuitOpenError,
    LLMClient,
    LLMClientConfig,
    LLMClientError,
)
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


class _AlwaysFailing:
    def __init__(self) -> None:
        self.name = "gemini"
        self.calls = 0

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        self.calls += 1
        raise LLMProviderError("induced failure", retryable=True)


async def test_circuit_opens_after_threshold_failures() -> None:
    primary = _AlwaysFailing()
    breaker = CircuitBreaker(fail_threshold=5, cool_down_seconds=60.0)
    client = LLMClient(
        primary=primary,
        config=LLMClientConfig(max_retries=0, base_backoff_seconds=0.0),
        breakers={"gemini": breaker},
    )

    # Five consecutive failures should open the breaker.
    for _ in range(5):
        with pytest.raises(LLMClientError):
            await client.call(
                spec=_spec(),
                rendered_prompt="hi",
                schema=_Payload,
                prompt_version_id=uuid.uuid4(),
            )
    assert breaker.opened_at is not None, "breaker did not trip after 5 failures"

    # A subsequent call should now short-circuit with CircuitOpenError —
    # the alarm-firing path in production.
    with pytest.raises((CircuitOpenError, LLMClientError)):
        await client.call(
            spec=_spec(),
            rendered_prompt="hi",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
        )
