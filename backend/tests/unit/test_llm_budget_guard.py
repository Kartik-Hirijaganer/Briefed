"""Unit tests for the daily-USD cost guard (Track A Phase 5)."""

from __future__ import annotations

import datetime as _dt
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.core import clock as _clock
from app.llm.client import (
    LLMBudgetExceededError,
    LLMBudgetGuard,
    LLMClient,
    PromptCallRecord,
)
from app.llm.providers.base import LLMCallResult, PromptSpec


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    reason: str


def _spec() -> PromptSpec:
    return PromptSpec(
        name="triage",
        version=1,
        content="hi",
        model="any",
        temperature=0.0,
        max_tokens=100,
        schema_ref="X",
    )


class _FakeProvider:
    name = "openrouter:gemini-flash"

    def __init__(self, *, cost_each_usd: Decimal) -> None:
        self._cost = cost_each_usd
        self.calls: int = 0

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        self.calls += 1
        return LLMCallResult(
            payload={"ok": True, "reason": "r"},
            tokens_in=1,
            tokens_out=1,
            tokens_cache_read=0,
            tokens_cache_write=0,
            cost_usd=self._cost,
            latency_ms=1,
            provider=self.name,
            model="any",
        )


def test_guard_disabled_when_cap_none() -> None:
    guard = LLMBudgetGuard(daily_cap_usd=None)
    guard.check_before_call()
    guard.record(Decimal("999"))
    guard.check_before_call()


def test_guard_trips_at_cap() -> None:
    guard = LLMBudgetGuard(daily_cap_usd=0.10)
    guard.check_before_call()  # ok at 0
    guard.record(Decimal("0.05"))
    guard.check_before_call()  # ok at 0.05
    guard.record(Decimal("0.06"))
    with pytest.raises(LLMBudgetExceededError) as exc:
        guard.check_before_call()
    assert exc.value.cap_usd == 0.10
    assert exc.value.spent_usd == Decimal("0.11")


def test_guard_resets_on_utc_day_rollover(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_today = date(2026, 4, 25)

    class _Now:
        d = fake_today

        def __call__(self) -> _dt.datetime:
            return _dt.datetime(self.d.year, self.d.month, self.d.day, 12, 0, 0)

    now = _Now()
    monkeypatch.setattr(_clock, "utcnow", now)
    # Re-import path: utcnow() is referenced inside client module.
    from app.llm import client as _client_module

    monkeypatch.setattr(_client_module, "utcnow", now)

    guard = LLMBudgetGuard(daily_cap_usd=0.10, day=fake_today)
    guard.record(Decimal("0.20"))
    with pytest.raises(LLMBudgetExceededError):
        guard.check_before_call()

    # Roll the day.
    now.d = date(2026, 4, 26)
    guard.check_before_call()  # cleared
    assert guard.spent_usd == Decimal("0")
    assert guard.day == date(2026, 4, 26)


def test_guard_record_zeros_on_day_rollover(monkeypatch: pytest.MonkeyPatch) -> None:
    """``record`` itself must reset on rollover, not just ``check_before_call``."""
    fake_today = date(2026, 4, 25)

    class _Now:
        d = fake_today

        def __call__(self) -> _dt.datetime:
            return _dt.datetime(self.d.year, self.d.month, self.d.day, 12, 0, 0)

    now = _Now()
    from app.llm import client as _client_module

    monkeypatch.setattr(_client_module, "utcnow", now)

    guard = LLMBudgetGuard(daily_cap_usd=0.10, day=fake_today)
    guard.record(Decimal("0.20"))
    assert guard.spent_usd == Decimal("0.20")

    now.d = date(2026, 4, 26)
    guard.record(Decimal("0.05"))
    assert guard.spent_usd == Decimal("0.05")
    assert guard.day == date(2026, 4, 26)


async def test_llm_client_short_circuits_when_cap_hit() -> None:
    provider = _FakeProvider(cost_each_usd=Decimal("0.40"))
    guard = LLMBudgetGuard(daily_cap_usd=0.50)
    client = LLMClient(primary=provider, budget_guard=guard)

    # First call eats $0.40 — under cap.
    await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert provider.calls == 1

    # Second call would push past cap — pre-check fires once spent >= cap.
    await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert provider.calls == 2  # second call still allowed (spend was 0.40 < 0.50)

    # Third call: spend is now 0.80, cap 0.50 → short-circuit.
    with pytest.raises(LLMBudgetExceededError):
        await client.call(
            spec=_spec(),
            rendered_prompt="hi",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
        )
    assert provider.calls == 2


async def test_multi_model_accrual_share_one_guard() -> None:
    primary = _FakeProvider(cost_each_usd=Decimal("0.30"))
    primary.name = "openrouter:gemini-flash"
    fallback = _FakeProvider(cost_each_usd=Decimal("0.40"))
    fallback.name = "openrouter:claude-haiku"
    guard = LLMBudgetGuard(daily_cap_usd=0.60)
    client = LLMClient(
        primary=primary,
        fallbacks=(fallback,),
        budget_guard=guard,
    )

    # Each call eats from the shared budget regardless of model used.
    await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert guard.spent_usd == Decimal("0.30")
    await client.call(
        spec=_spec(),
        rendered_prompt="hi",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert guard.spent_usd == Decimal("0.60")
    with pytest.raises(LLMBudgetExceededError):
        await client.call(
            spec=_spec(),
            rendered_prompt="hi",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
        )


async def test_guard_only_records_on_success() -> None:
    """Failed calls do not deduct from the daily budget."""

    class _AlwaysFail:
        name = "openrouter:flaky"

        async def complete_json(
            self,
            spec: PromptSpec,
            *,
            rendered_prompt: str,
        ) -> LLMCallResult:
            from app.llm.providers.base import LLMProviderError

            raise LLMProviderError("nope", retryable=False)

    provider: Any = _AlwaysFail()
    guard = LLMBudgetGuard(daily_cap_usd=0.10)
    client = LLMClient(primary=provider, budget_guard=guard)
    logs: list[PromptCallRecord] = []

    async def log(record: PromptCallRecord) -> None:
        logs.append(record)

    from app.llm.client import LLMClientError

    with pytest.raises(LLMClientError):
        await client.call(
            spec=_spec(),
            rendered_prompt="hi",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
            log_call=log,
        )
    assert guard.spent_usd == Decimal("0")
