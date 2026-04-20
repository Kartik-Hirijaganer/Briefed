"""Unit tests for the batch driver (plan §14 Phase 3).

Covers submit-poll-parse happy path, partial-per-request failures, and
the timeout path — the exit-criterion test case for "Batch API submit,
poll, parse; partial failure handled".
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.llm.providers.base import LLMProviderError, PromptSpec
from app.services.summarization.batch import (
    BatchDriver,
    BatchRequest,
    BatchResult,
    BatchTimeoutError,
    InMemoryBatchProvider,
    SyntheticBatchProvider,
    build_call_result,
)


def _spec() -> PromptSpec:
    return PromptSpec(
        name="summarize_relevant",
        version=1,
        content="body",
        model="gemini-1.5-flash",
        max_tokens=400,
    )


def _ok_result(request_id: str) -> BatchResult:
    spec = _spec()
    return BatchResult(
        request_id=request_id,
        ok=True,
        call_result=build_call_result(
            payload={
                "tldr": "ok",
                "confidence": 0.9,
                "key_points": (),
                "action_items": (),
                "entities": (),
            },
            spec=spec,
            provider="in_memory_batch",
            tokens_in=50,
            tokens_out=20,
            cost_usd=Decimal("0.001000"),
        ),
    )


@pytest.mark.asyncio
async def test_submit_and_poll_happy_path() -> None:
    provider = InMemoryBatchProvider(
        responses={"batch-1": (_ok_result("a"), _ok_result("b"))},
        polls_until_terminal=1,
    )
    driver = BatchDriver(
        provider=provider,
        poll_interval_seconds=0.0,
        max_wait_seconds=5,
    )
    submission, results = await driver.submit_and_poll(
        (
            BatchRequest(request_id="a", spec=_spec(), rendered_prompt="x"),
            BatchRequest(request_id="b", spec=_spec(), rendered_prompt="y"),
        ),
    )
    assert submission.status == "completed"
    assert {r.request_id for r in results} == {"a", "b"}
    assert all(r.ok for r in results)


@pytest.mark.asyncio
async def test_submit_and_poll_partial_failure() -> None:
    provider = InMemoryBatchProvider(
        responses={
            "batch-1": (
                _ok_result("a"),
                BatchResult(
                    request_id="b",
                    ok=False,
                    call_result=None,
                    error="schema mismatch",
                ),
            ),
        },
        polls_until_terminal=2,
    )
    driver = BatchDriver(
        provider=provider,
        poll_interval_seconds=0.0,
        max_wait_seconds=5,
    )
    _submission, results = await driver.submit_and_poll(
        (
            BatchRequest(request_id="a", spec=_spec(), rendered_prompt="x"),
            BatchRequest(request_id="b", spec=_spec(), rendered_prompt="y"),
        ),
    )
    assert [r.ok for r in results] == [True, False]
    assert results[1].error == "schema mismatch"


@pytest.mark.asyncio
async def test_submit_and_poll_raises_on_timeout() -> None:
    provider = InMemoryBatchProvider(
        responses={"batch-1": ()},
        polls_until_terminal=100,
    )
    driver = BatchDriver(
        provider=provider,
        poll_interval_seconds=0.0,
        max_wait_seconds=-1,  # force the timeout branch after the first sleep.
    )
    with pytest.raises(BatchTimeoutError):
        await driver.submit_and_poll(
            (BatchRequest(request_id="a", spec=_spec(), rendered_prompt="x"),),
        )


@pytest.mark.asyncio
async def test_empty_requests_short_circuits_without_submission() -> None:
    provider = InMemoryBatchProvider()
    driver = BatchDriver(provider=provider, poll_interval_seconds=0.0)
    submission, results = await driver.submit_and_poll(())
    assert submission.status == "completed"
    assert results == ()
    assert provider.submitted == []


@pytest.mark.asyncio
async def test_synthetic_provider_handles_per_request_errors() -> None:
    async def _caller(req: BatchRequest):
        if req.request_id == "bad":
            raise LLMProviderError("boom", retryable=False)
        return build_call_result(
            payload={"tldr": "ok", "confidence": 0.9},
            spec=req.spec,
            provider="synthetic",
            tokens_in=1,
            tokens_out=1,
        )

    provider = SyntheticBatchProvider(
        name="synthetic_gemini",
        sync_caller=_caller,
    )
    driver = BatchDriver(
        provider=provider,
        poll_interval_seconds=0.0,
        max_wait_seconds=5,
    )
    _submission, results = await driver.submit_and_poll(
        (
            BatchRequest(request_id="good", spec=_spec(), rendered_prompt="x"),
            BatchRequest(request_id="bad", spec=_spec(), rendered_prompt="y"),
        ),
    )
    outcomes = {r.request_id: r for r in results}
    assert outcomes["good"].ok is True
    assert outcomes["bad"].ok is False
    assert "boom" in outcomes["bad"].error
