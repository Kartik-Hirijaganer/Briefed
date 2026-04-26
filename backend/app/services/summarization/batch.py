"""Provider-agnostic Batch API driver (plan §14 Phase 3).

The driver submits a set of summarize prompts to a provider's batch
surface, polls for completion, and parses the results into
:class:`app.llm.providers.base.LLMCallResult` objects. It is delibrately
provider-agnostic: concrete providers (Gemini, Anthropic direct,
OpenRouter, Bedrock) implement the :class:`BatchProvider` protocol.

The sync-fallback path (per plan §14 Phase 3 risks) is owned by the
caller: if :meth:`BatchDriver.submit_and_poll` raises
:class:`BatchTimeoutError` the caller re-runs the items via
:func:`app.services.summarization.relevant.summarize_email` one at a
time. The driver itself never retries — retries live in
:class:`app.llm.client.LLMClient`.

A minimal in-memory :class:`InMemoryBatchProvider` ships with the
module so unit tests can exercise the full happy-path, partial-failure,
and timeout branches without hitting a real provider. Phase 3 exit
criteria require "Batch API submit, poll, parse; partial failure
handled" — this is where that coverage lives.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.core.logging import get_logger
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.observability.metrics import emit_batch_lifecycle_metric

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping


logger = get_logger(__name__)


class BatchTimeoutError(LLMProviderError):
    """Raised when a batch did not reach a terminal state in time."""

    def __init__(self, batch_id: str, elapsed_seconds: float) -> None:
        """Record the batch id + elapsed time for diagnostics.

        Args:
            batch_id: Provider-returned batch identifier.
            elapsed_seconds: Seconds spent polling before giving up.
        """
        super().__init__(
            f"batch {batch_id} did not complete within {elapsed_seconds:.0f}s",
            retryable=False,
        )
        self.batch_id = batch_id
        self.elapsed_seconds = elapsed_seconds


@dataclass(frozen=True)
class BatchRequest:
    """One item inside a batch submission.

    Attributes:
        request_id: Stable per-item identifier (usually the email id).
        spec: Versioned prompt spec.
        rendered_prompt: Fully interpolated prompt text.
    """

    request_id: str
    spec: PromptSpec
    rendered_prompt: str


@dataclass(frozen=True)
class BatchResult:
    """Outcome of one request inside a processed batch.

    Attributes:
        request_id: Mirrors :attr:`BatchRequest.request_id`.
        ok: ``True`` for successful calls, ``False`` for per-item failures.
        call_result: Populated when ``ok=True``. ``None`` on failure.
        error: Populated when ``ok=False``. ``""`` on success.
    """

    request_id: str
    ok: bool
    call_result: LLMCallResult | None
    error: str = ""


@dataclass
class BatchSubmission:
    """In-flight batch metadata returned by the provider at submit time.

    Attributes:
        batch_id: Provider-returned identifier used for polling.
        status: Current provider status string.
        submitted_at: Monotonic timestamp at submit time.
        request_count: Count of items in the submission.
    """

    batch_id: str
    status: str
    submitted_at: float
    request_count: int


@runtime_checkable
class BatchProvider(Protocol):
    """Provider surface the driver depends on.

    Concrete adapters map provider-specific APIs onto this protocol so
    :class:`BatchDriver` stays one-shot-async + testable.
    """

    name: str

    async def submit(self, requests: tuple[BatchRequest, ...]) -> BatchSubmission:
        """Submit a batch and return the initial :class:`BatchSubmission`."""
        ...

    async def poll(self, batch_id: str) -> BatchSubmission:
        """Return the latest :class:`BatchSubmission` for ``batch_id``."""
        ...

    async def fetch_results(self, batch_id: str) -> tuple[BatchResult, ...]:
        """Fetch per-request outcomes once the batch is terminal."""
        ...

    async def cancel(self, batch_id: str) -> None:
        """Best-effort cancel; raises :class:`LLMProviderError` on hard fail."""
        ...


_TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "canceled"})
"""Provider-neutral status values at which polling stops."""


@dataclass
class BatchDriver:
    """Orchestrates one submit-poll-parse lifecycle.

    Attributes:
        provider: Concrete :class:`BatchProvider` adapter.
        poll_interval_seconds: Seconds between poll attempts.
        max_wait_seconds: Upper bound for the entire poll loop.
    """

    provider: BatchProvider
    poll_interval_seconds: float = 30.0
    max_wait_seconds: float = 6 * 60 * 60  # 6 h per plan Phase 3.

    async def submit_and_poll(
        self,
        requests: tuple[BatchRequest, ...],
    ) -> tuple[BatchSubmission, tuple[BatchResult, ...]]:
        """Submit ``requests`` and block until the batch is terminal.

        Args:
            requests: Batch items.

        Returns:
            Tuple ``(submission, results)`` — :attr:`BatchSubmission.status`
            is one of the terminal states; ``results`` carries one entry
            per request.

        Raises:
            BatchTimeoutError: When the poll loop exhausts
                :attr:`max_wait_seconds`.
        """
        if not requests:
            empty = BatchSubmission(
                batch_id="",
                status="completed",
                submitted_at=time.monotonic(),
                request_count=0,
            )
            return empty, ()

        submission = await self.provider.submit(requests)
        emit_batch_lifecycle_metric(
            phase="submitted",
            requests=len(requests),
            succeeded=0,
            failed=0,
            provider=self.provider.name,
        )
        logger.info(
            "summarize.batch.submitted",
            batch_id=submission.batch_id,
            request_count=submission.request_count,
            provider=self.provider.name,
        )

        started = time.monotonic()
        status = submission.status
        latest = submission
        while status not in _TERMINAL_STATES:
            elapsed = time.monotonic() - started
            if elapsed > self.max_wait_seconds:
                await self._safe_cancel(submission.batch_id)
                raise BatchTimeoutError(
                    batch_id=submission.batch_id,
                    elapsed_seconds=elapsed,
                )
            await asyncio.sleep(self.poll_interval_seconds)
            latest = await self.provider.poll(submission.batch_id)
            status = latest.status

        results = await self.provider.fetch_results(submission.batch_id)
        succeeded = sum(1 for r in results if r.ok)
        failed = sum(1 for r in results if not r.ok)
        emit_batch_lifecycle_metric(
            phase=status,
            requests=len(requests),
            succeeded=succeeded,
            failed=failed,
            provider=self.provider.name,
        )
        logger.info(
            "summarize.batch.completed",
            batch_id=submission.batch_id,
            status=status,
            succeeded=succeeded,
            failed=failed,
            provider=self.provider.name,
        )
        return latest, results

    async def _safe_cancel(self, batch_id: str) -> None:
        """Cancel without re-raising; logging is sufficient on timeout."""
        try:
            await self.provider.cancel(batch_id)
        except LLMProviderError as exc:
            logger.warning(
                "summarize.batch.cancel_failed",
                batch_id=batch_id,
                error=str(exc),
            )


@dataclass
class InMemoryBatchProvider:
    """Test-only batch provider (plan §14 Phase 3 exit criterion).

    Yields the pre-registered results in ``responses`` the first time
    :meth:`fetch_results` is called. Unknown batch ids raise
    :class:`LLMProviderError`. Used by unit tests to exercise partial
    failure + timeout branches.

    Attributes:
        name: Provider slug surfaced to telemetry.
        responses: Per-batch-id result mapping.
        polls_until_terminal: How many polls return ``"running"`` before
            flipping to the configured terminal status.
        terminal_status: Status the provider returns once terminal.
        submitted: Accumulates every submission for assertion in tests.
    """

    name: str = "in_memory_batch"
    responses: dict[str, tuple[BatchResult, ...]] = field(default_factory=dict)
    polls_until_terminal: int = 1
    terminal_status: str = "completed"
    submitted: list[BatchSubmission] = field(default_factory=list)
    _poll_counts: dict[str, int] = field(default_factory=dict)

    async def submit(self, requests: tuple[BatchRequest, ...]) -> BatchSubmission:
        """Register the submission and return an initial status."""
        batch_id = f"batch-{len(self.submitted) + 1}"
        submission = BatchSubmission(
            batch_id=batch_id,
            status="submitted",
            submitted_at=time.monotonic(),
            request_count=len(requests),
        )
        self.submitted.append(submission)
        self._poll_counts[batch_id] = 0
        return submission

    async def poll(self, batch_id: str) -> BatchSubmission:
        """Advance the poll counter + return the current status."""
        if batch_id not in self._poll_counts:
            raise LLMProviderError(f"unknown batch {batch_id}", retryable=False)
        self._poll_counts[batch_id] += 1
        status = (
            self.terminal_status
            if self._poll_counts[batch_id] >= self.polls_until_terminal
            else "running"
        )
        matching = next(s for s in self.submitted if s.batch_id == batch_id)
        return BatchSubmission(
            batch_id=matching.batch_id,
            status=status,
            submitted_at=matching.submitted_at,
            request_count=matching.request_count,
        )

    async def fetch_results(self, batch_id: str) -> tuple[BatchResult, ...]:
        """Return the pre-registered results."""
        return self.responses.get(batch_id, ())

    async def cancel(self, batch_id: str) -> None:
        """No-op cancel path."""
        self.responses.pop(batch_id, None)


@dataclass
class SyntheticBatchProvider:
    """Provider-agnostic shim that executes a batch via the sync path.

    Used when the primary provider does not expose a batch endpoint but
    the caller still wants the batch-framed SummariesRepo write path.
    Each request is dispatched through ``sync_caller`` under an
    ``asyncio.Semaphore`` so we stay inside the Lambda concurrency
    budget.

    Attributes:
        name: Provider slug.
        sync_caller: Async callback executed per request. Receives the
            :class:`BatchRequest`; must return an :class:`LLMCallResult`
            or raise :class:`LLMProviderError` on failure.
        max_concurrency: Cap on simultaneous ``sync_caller`` invocations.
    """

    name: str
    sync_caller: Any
    max_concurrency: int = 4
    _stash: dict[str, tuple[BatchResult, ...]] = field(default_factory=dict)
    _seq: int = 0

    async def submit(
        self,
        requests: tuple[BatchRequest, ...],
    ) -> BatchSubmission:
        """Execute all requests up-front; store results for the poll."""
        self._seq += 1
        batch_id = f"synthetic-{self._seq}"
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _run(req: BatchRequest) -> BatchResult:
            async with semaphore:
                try:
                    result: LLMCallResult = await self.sync_caller(req)
                except LLMProviderError as exc:
                    return BatchResult(
                        request_id=req.request_id,
                        ok=False,
                        call_result=None,
                        error=str(exc),
                    )
            return BatchResult(
                request_id=req.request_id,
                ok=True,
                call_result=result,
            )

        gathered = await asyncio.gather(*(_run(r) for r in requests))
        self._stash[batch_id] = tuple(gathered)
        return BatchSubmission(
            batch_id=batch_id,
            status="completed",
            submitted_at=time.monotonic(),
            request_count=len(requests),
        )

    async def poll(self, batch_id: str) -> BatchSubmission:
        """Synthetic batches are already terminal at submit time."""
        return BatchSubmission(
            batch_id=batch_id,
            status="completed",
            submitted_at=time.monotonic(),
            request_count=len(self._stash.get(batch_id, ())),
        )

    async def fetch_results(self, batch_id: str) -> tuple[BatchResult, ...]:
        """Return the stashed results from :meth:`submit`."""
        return self._stash.get(batch_id, ())

    async def cancel(self, batch_id: str) -> None:
        """Drop the stashed results."""
        self._stash.pop(batch_id, None)


def build_call_result(
    *,
    payload: Mapping[str, Any],
    spec: PromptSpec,
    provider: str,
    tokens_in: int,
    tokens_out: int,
    tokens_cache_read: int = 0,
    tokens_cache_write: int = 0,
    cost_usd: Decimal = Decimal("0"),
    latency_ms: int = 0,
) -> LLMCallResult:
    """Helper for adapters that return pre-parsed payloads.

    Args:
        payload: Parsed JSON dict from the batch response.
        spec: Originating :class:`PromptSpec`.
        provider: Provider slug.
        tokens_in: Input tokens billed.
        tokens_out: Output tokens billed.
        tokens_cache_read: Cached input tokens (0 if unsupported).
        tokens_cache_write: Cache-write tokens.
        cost_usd: Provider-reported or locally-computed cost.
        latency_ms: Wall-clock latency (or ``0`` for batch).

    Returns:
        :class:`LLMCallResult` wired for the downstream validator.
    """
    return LLMCallResult(
        payload=dict(payload),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_cache_read=tokens_cache_read,
        tokens_cache_write=tokens_cache_write,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        provider=provider,
        model=spec.model,
    )


__all__ = [
    "BatchDriver",
    "BatchProvider",
    "BatchRequest",
    "BatchResult",
    "BatchSubmission",
    "BatchTimeoutError",
    "InMemoryBatchProvider",
    "SyntheticBatchProvider",
    "build_call_result",
]
