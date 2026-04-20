"""``LLMClient`` — retries + circuit breaker + fallback chain + cost log.

One of the five 100%-coverage modules (plan §20.1). Every LLM call in
Briefed flows through this client so:

* retries are consistent (exponential backoff with jitter; 3 attempts
  on ``retryable=True`` errors);
* a :class:`CircuitBreaker` trips open after 5 consecutive failures and
  recovers after a configurable cool-down (plan §14 Phase 2 exit
  criteria);
* the fallback chain (``settings.llm.fallback_chain``) kicks in when the
  primary has opened its breaker or returned a non-retryable error;
* every call writes one :class:`app.db.models.PromptCallLog` row with
  tokens + cost telemetry for CloudWatch dashboards (§8);
* provider-specific hard caps (Claude Haiku 4.5 at 100 calls/day, plan
  §19.15) are enforced in-memory.

The client is deliberately DB-aware via an injected logger callback so
unit tests can assert on write counts without spinning up a session.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.llm.providers.base import (
    LLMCallResult,
    LLMProvider,
    LLMProviderError,
    PromptSpec,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Awaitable, Callable


logger = get_logger(__name__)


class LLMClientError(Exception):
    """Raised when every provider in the fallback chain fails."""


class CircuitOpenError(LLMProviderError):
    """The breaker is open for this provider — caller must fall through."""

    def __init__(self, provider: str, *, reset_at: float) -> None:
        """Store the reset deadline for diagnostics.

        Args:
            provider: Provider name that tripped.
            reset_at: ``time.monotonic()`` value past which the breaker
                transitions to half-open.
        """
        super().__init__(f"circuit open for {provider}", retryable=False)
        self.provider = provider
        self.reset_at = reset_at


@dataclass
class CircuitBreaker:
    """Minimal consecutive-failure circuit breaker.

    Opens after :attr:`fail_threshold` consecutive failures; stays open
    for :attr:`cool_down_seconds` before moving to *half-open* (a single
    probe call). A success in either state resets the counter.

    Attributes:
        fail_threshold: Failures in a row that trip the breaker.
        cool_down_seconds: Seconds to stay fully open.
        consecutive_failures: Failure counter; reset on success.
        opened_at: ``time.monotonic()`` when the breaker opened, else
            ``None`` when closed.
    """

    fail_threshold: int = 5
    cool_down_seconds: float = 60.0
    consecutive_failures: int = 0
    opened_at: float | None = None

    def before_call(self) -> None:
        """Check the current state and raise when the breaker is open.

        Raises:
            CircuitOpenError: When the breaker is open and not yet in
                half-open probe mode.
        """
        if self.opened_at is None:
            return
        now = time.monotonic()
        if now - self.opened_at < self.cool_down_seconds:
            raise CircuitOpenError(
                provider="<self>",
                reset_at=self.opened_at + self.cool_down_seconds,
            )

    def record_success(self) -> None:
        """Clear the failure counter + close the breaker."""
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        """Bump the failure counter; trip the breaker at the threshold."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.fail_threshold:
            self.opened_at = time.monotonic()


@dataclass
class RateCap:
    """Daily call cap for a specific provider (e.g. Claude Haiku).

    Counts in-memory across the Lambda warm window. Reset on date flip.
    Downstream runbook rotates caps when the warm-window boundary is
    unreliable.

    Attributes:
        max_calls: Cap per calendar day.
        day: Current calendar date under count.
        used: Calls made today.
    """

    max_calls: int
    day: date = field(default_factory=lambda: utcnow().date())
    used: int = 0

    def consume(self) -> None:
        """Record one call; raise when the cap is exhausted.

        Raises:
            LLMProviderError: ``retryable=False`` when the cap is hit.
        """
        today = utcnow().date()
        if today != self.day:
            self.day = today
            self.used = 0
        if self.used >= self.max_calls:
            raise LLMProviderError(
                f"daily rate cap exhausted ({self.used}/{self.max_calls})",
                retryable=False,
            )
        self.used += 1


@dataclass
class LLMClientConfig:
    """Tunables for :class:`LLMClient`.

    Attributes:
        max_retries: Upper bound on retries per provider per call.
        base_backoff_seconds: Seed for exponential backoff.
        max_backoff_seconds: Cap for exponential backoff.
    """

    max_retries: int = 3
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 6.0


PromptLogger = "Callable[[PromptCallRecord], Awaitable[None]]"
"""Type alias used in docstrings; runtime type hinted inline below."""


@dataclass(frozen=True)
class PromptCallRecord:
    """Row payload handed to the persistence callback.

    Mirrors :class:`app.db.models.PromptCallLog` one-for-one so the
    callback can do a straight attribute-to-column mapping.

    Attributes:
        prompt_version_id: ``prompt_versions.id`` FK.
        email_id: Optional email scope.
        run_id: Optional digest-run scope.
        model: Model identifier returned by the provider.
        tokens_in: Billed input tokens.
        tokens_out: Billed output tokens.
        tokens_cache_read: Cache hits.
        tokens_cache_write: Cache writes.
        cost_usd: Provider-computed or locally-estimated USD cost.
        latency_ms: Wall clock latency.
        status: ``ok`` / ``fallback`` / ``error`` / ``skipped``.
        provider: Provider slug.
    """

    prompt_version_id: UUID
    email_id: UUID | None
    run_id: UUID | None
    model: str
    tokens_in: int
    tokens_out: int
    tokens_cache_read: int
    tokens_cache_write: int
    cost_usd: Decimal
    latency_ms: int
    status: str
    provider: str


@dataclass(frozen=True)
class ClientResponse:
    """Successful result of :meth:`LLMClient.call`.

    Attributes:
        parsed: Pydantic-validated payload.
        call_result: The underlying :class:`LLMCallResult`.
        record: :class:`PromptCallRecord` mirror of the persisted row.
        fallback_used: True when the primary failed and the fallback
            ran successfully.
    """

    parsed: BaseModel
    call_result: LLMCallResult
    record: PromptCallRecord
    fallback_used: bool


class LLMClient:
    """Facade over the provider chain.

    Attributes:
        primary: First provider tried on every call.
        fallbacks: Ordered fallback chain (empty tuple = no fallback).
    """

    def __init__(
        self,
        *,
        primary: LLMProvider,
        fallbacks: tuple[LLMProvider, ...] = (),
        config: LLMClientConfig | None = None,
        breakers: dict[str, CircuitBreaker] | None = None,
        rate_caps: dict[str, RateCap] | None = None,
    ) -> None:
        """Wire up providers + reliability primitives.

        Args:
            primary: First provider tried on every call.
            fallbacks: Additional providers tried on primary failure.
            config: Retry tunables. Defaults to :class:`LLMClientConfig`.
            breakers: Optional pre-populated breaker map (tests).
            rate_caps: Optional pre-populated rate-cap map (tests).
        """
        self.primary = primary
        self.fallbacks = fallbacks
        self._config = config or LLMClientConfig()
        self._breakers: dict[str, CircuitBreaker] = breakers or {}
        self._rate_caps: dict[str, RateCap] = rate_caps or {}

    def breaker_for(self, provider: str) -> CircuitBreaker:
        """Return the (lazily-created) breaker for ``provider``."""
        return self._breakers.setdefault(provider, CircuitBreaker())

    async def call(
        self,
        *,
        spec: PromptSpec,
        rendered_prompt: str,
        schema: type[BaseModel],
        prompt_version_id: UUID,
        email_id: UUID | None = None,
        run_id: UUID | None = None,
        log_call: Callable[[PromptCallRecord], Awaitable[None]] | None = None,
    ) -> ClientResponse:
        """Execute one LLM call with retries + fallback + cost log.

        Args:
            spec: :class:`PromptSpec` for the call.
            rendered_prompt: Fully interpolated prompt text.
            schema: Pydantic model the payload must validate against.
            prompt_version_id: FK into ``prompt_versions``.
            email_id: Optional email scope for the log row.
            run_id: Optional digest-run scope.
            log_call: Optional async callback that persists
                :class:`PromptCallRecord` rows. ``None`` during pure
                unit tests; workers inject a session-backed callback.

        Returns:
            :class:`ClientResponse` with the parsed payload.

        Raises:
            LLMClientError: When every provider fails.
        """
        chain: tuple[LLMProvider, ...] = (self.primary, *self.fallbacks)
        errors: list[str] = []
        for index, provider in enumerate(chain):
            try:
                call_result = await self._call_provider(
                    provider=provider,
                    spec=spec,
                    rendered_prompt=rendered_prompt,
                )
            except LLMProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.warning(
                    "llm.provider.failed",
                    provider=provider.name,
                    error=str(exc),
                    position=index,
                )
                continue

            try:
                parsed = schema.model_validate(call_result.payload)
            except ValidationError as exc:
                errors.append(f"{provider.name}: schema mismatch {exc}")
                self.breaker_for(provider.name).record_failure()
                logger.warning(
                    "llm.provider.schema_mismatch",
                    provider=provider.name,
                    error=str(exc),
                )
                continue

            record = PromptCallRecord(
                prompt_version_id=prompt_version_id,
                email_id=email_id,
                run_id=run_id,
                model=call_result.model,
                tokens_in=call_result.tokens_in,
                tokens_out=call_result.tokens_out,
                tokens_cache_read=call_result.tokens_cache_read,
                tokens_cache_write=call_result.tokens_cache_write,
                cost_usd=call_result.cost_usd,
                latency_ms=call_result.latency_ms,
                status="ok" if index == 0 else "fallback",
                provider=call_result.provider,
            )
            if log_call is not None:
                await log_call(record)
            return ClientResponse(
                parsed=parsed,
                call_result=call_result,
                record=record,
                fallback_used=index > 0,
            )

        if log_call is not None:
            # Best-effort "error" row so the audit log sees the failure.
            await log_call(
                PromptCallRecord(
                    prompt_version_id=prompt_version_id,
                    email_id=email_id,
                    run_id=run_id,
                    model=spec.model,
                    tokens_in=0,
                    tokens_out=0,
                    tokens_cache_read=0,
                    tokens_cache_write=0,
                    cost_usd=Decimal("0"),
                    latency_ms=0,
                    status="error",
                    provider=chain[0].name if chain else "",
                ),
            )
        raise LLMClientError("every provider failed: " + " | ".join(errors))

    async def _call_provider(
        self,
        *,
        provider: LLMProvider,
        spec: PromptSpec,
        rendered_prompt: str,
    ) -> LLMCallResult:
        """Run ``provider`` with retries + breaker + rate cap.

        Args:
            provider: Provider to run.
            spec: :class:`PromptSpec` for the call.
            rendered_prompt: Fully interpolated prompt text.

        Returns:
            :class:`LLMCallResult` on success.

        Raises:
            LLMProviderError: When all retries are exhausted, or when
                the breaker is open, or when the daily cap is hit.
        """
        breaker = self.breaker_for(provider.name)
        try:
            breaker.before_call()
        except CircuitOpenError:
            # Re-raise as LLMProviderError so the outer chain catches it.
            raise LLMProviderError(
                f"circuit open for {provider.name}",
                retryable=False,
            ) from None

        cap = self._rate_caps.get(provider.name)
        if cap is not None:
            cap.consume()

        attempt = 0
        last_exc: LLMProviderError | None = None
        while attempt <= self._config.max_retries:
            try:
                result = await provider.complete_json(spec, rendered_prompt=rendered_prompt)
            except LLMProviderError as exc:
                last_exc = exc
                breaker.record_failure()
                if not exc.retryable or attempt == self._config.max_retries:
                    raise
                await asyncio.sleep(self._backoff(attempt))
                attempt += 1
                continue
            breaker.record_success()
            return result

        # Defensive — the loop above always raises or returns.
        assert last_exc is not None  # pragma: no cover
        raise last_exc  # pragma: no cover

    def _backoff(self, attempt: int) -> float:
        """Compute the next backoff delay with full jitter.

        Args:
            attempt: Zero-based attempt index.

        Returns:
            Delay in seconds.
        """
        base = self._config.base_backoff_seconds * (2**attempt)
        capped = min(base, self._config.max_backoff_seconds)
        return random.uniform(0, capped)


def render_prompt(spec: PromptSpec, variables: dict[str, Any]) -> str:
    """Interpolate ``{{variable}}`` placeholders into ``spec.content``.

    We keep templating deliberately minimal — the prompt files are
    markdown with double-mustache placeholders so an accidental single
    mustache (e.g. a user-supplied email body containing ``{curly}``)
    cannot inject template logic.

    Args:
        spec: Versioned prompt spec.
        variables: Mapping of placeholder names to replacement strings.
            Values are stringified via ``str()``; no HTML escaping.

    Returns:
        The rendered prompt.

    Raises:
        KeyError: If the prompt references a missing variable.
    """
    rendered = spec.content
    for placeholder in _iter_placeholders(rendered):
        if placeholder not in variables:
            raise KeyError(f"prompt {spec.name} missing variable {placeholder}")
        rendered = rendered.replace(
            "{{" + placeholder + "}}",
            str(variables[placeholder]),
        )
    return rendered


_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
"""Regex matching ``{{variable}}`` placeholders in a prompt template."""


def _iter_placeholders(text: str) -> set[str]:
    """Return the set of ``{{var}}`` names referenced in ``text``."""
    return set(_PLACEHOLDER_RE.findall(text))


__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "ClientResponse",
    "LLMClient",
    "LLMClientConfig",
    "LLMClientError",
    "PromptCallRecord",
    "RateCap",
    "render_prompt",
]
