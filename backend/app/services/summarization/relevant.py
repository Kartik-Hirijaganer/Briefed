"""Per-email summarizer (plan §14 Phase 3).

Given one :class:`app.db.models.Email`, this module:

1. Reads the classification bucket (must_read / good_to_read /
   newsletter).
2. Renders the ``summarize_relevant`` prompt from the registry.
3. Calls :class:`app.llm.client.LLMClient`. The client's provider chain
   (Gemini primary, Haiku gated fallback) + circuit breaker drive
   retries; this module stays single-purpose.
4. Validates the :class:`app.llm.schemas.EmailSummary` payload.
5. Writes a :class:`app.db.models.Summary` row via
   :class:`app.services.summarization.repository.SummariesRepo`
   (body_md + entities envelope-encrypted).
6. Appends a :class:`app.db.models.PromptCallLog` row (cost + cache
   telemetry).

Confidence < 0.55 does **not** suppress the write — we still want the
row so the digest composer can flag it as low-confidence. The digest
layer (Phase 3+) reads ``summaries.confidence`` and chooses whether to
display the TL;DR or fall back to the snippet.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import Classification, Email, EmailContentBlob, PromptCallLog, Summary
from app.llm.client import LLMClient, LLMClientError, PromptCallRecord, render_prompt
from app.llm.schemas import EmailSummary
from app.services.ingestion.content import decrypt_excerpt
from app.services.summarization.repository import SummariesRepo, SummaryEmailWrite

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher
    from app.services.prompts.registry import RegisteredPrompt


logger = get_logger(__name__)

_NEEDS_REVIEW_THRESHOLD = 0.55
"""Below this confidence the row is written but flagged (plan §6)."""


@dataclass(frozen=True)
class SummarizeInputs:
    """Everything the pipeline needs to summarize one email.

    Attributes:
        email_id: Target email.
        user_id: Owner — bound into the encryption context.
        prompt: Loaded :class:`RegisteredPrompt` for ``summarize_relevant``.
        prompt_version_id: ``prompt_versions.id`` matching ``prompt``.
        llm: Configured :class:`LLMClient`.
        repo: Encrypt-on-write :class:`SummariesRepo`.
        batch_id: Optional Batch API job id; set by the batch driver.
        content_cipher: Optional content-at-rest cipher for body excerpts.
    """

    email_id: UUID
    user_id: UUID
    prompt: RegisteredPrompt
    prompt_version_id: UUID
    llm: LLMClient
    repo: SummariesRepo
    batch_id: str | None = None
    content_cipher: EnvelopeCipher | None = None


@dataclass(frozen=True)
class SummarizeOutcome:
    """Result returned to the worker handler.

    Attributes:
        email_id: Echoed back for convenience.
        ok: ``True`` when a summary row was written.
        confidence: ``float`` in ``[0, 1]``; ``0.0`` on LLM failure.
        tokens_in: Tokens billed on input.
        tokens_out: Tokens billed on output.
        cost_usd: Summed cost of the summarize call.
        cache_hit: Whether the provider reported cache-read tokens.
        fallback_used: True when the LLM fallback adapter produced the
            row (the primary failed but recovery succeeded).
        skipped_reason: Populated when ``ok=False``.
    """

    email_id: UUID
    ok: bool
    confidence: float
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    cache_hit: bool
    fallback_used: bool
    skipped_reason: str = ""


async def summarize_email(
    inputs: SummarizeInputs,
    *,
    session: AsyncSession,
    run_id: UUID | None = None,
) -> SummarizeOutcome:
    """Summarize one classified email end-to-end.

    Args:
        inputs: Collaborator bundle.
        session: Active async session (caller owns commit).
        run_id: Optional digest-run scope for the prompt-call-log row.

    Returns:
        :class:`SummarizeOutcome`.

    Raises:
        LookupError: When the target email row has vanished.
    """
    email_row = await session.get(Email, inputs.email_id)
    if email_row is None:
        raise LookupError(f"email {inputs.email_id} not found")

    if await _has_email_summary(session, email_id=inputs.email_id):
        return SummarizeOutcome(
            email_id=inputs.email_id,
            ok=False,
            confidence=0.0,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            cache_hit=False,
            fallback_used=False,
            skipped_reason="already summarized",
        )

    classification = await _load_classification(session, email_id=inputs.email_id)
    category = classification.label if classification is not None else "good_to_read"

    rendered = render_prompt(
        inputs.prompt.spec,
        variables={
            "category": category,
            "from_addr": email_row.from_addr,
            "subject": email_row.subject,
            "plain_text_excerpt": _excerpt_for(
                email_row,
                user_id=inputs.user_id,
                cipher=inputs.content_cipher,
            ),
        },
    )

    async def _log_call(record: PromptCallRecord) -> None:
        await _persist_call_log(session=session, record=record, run_id=run_id)

    started = utcnow()
    try:
        response = await inputs.llm.call(
            spec=inputs.prompt.spec,
            rendered_prompt=rendered,
            schema=EmailSummary,
            prompt_version_id=inputs.prompt_version_id,
            email_id=inputs.email_id,
            run_id=run_id,
            log_call=_log_call,
        )
    except LLMClientError as exc:
        logger.warning(
            "summarize.email.llm_failed",
            email_id=str(inputs.email_id),
            error=str(exc),
        )
        return SummarizeOutcome(
            email_id=inputs.email_id,
            ok=False,
            confidence=0.0,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            cache_hit=False,
            fallback_used=False,
            skipped_reason=str(exc),
        )

    summary = response.parsed
    assert isinstance(summary, EmailSummary)
    body_md = _render_body_md(summary)
    cache_hit = response.call_result.tokens_cache_read > 0

    await inputs.repo.upsert_email(
        session,
        SummaryEmailWrite(
            email_id=inputs.email_id,
            user_id=inputs.user_id,
            prompt_version_id=inputs.prompt_version_id,
            model=response.call_result.model,
            tokens_in=response.call_result.tokens_in,
            tokens_out=response.call_result.tokens_out,
            body_md=body_md,
            entities=tuple(summary.entities),
            confidence=_to_decimal(summary.confidence),
            cache_hit=cache_hit,
            batch_id=inputs.batch_id,
        ),
    )

    logger.info(
        "summarize.email.completed",
        email_id=str(inputs.email_id),
        confidence=summary.confidence,
        tokens_in=response.call_result.tokens_in,
        tokens_out=response.call_result.tokens_out,
        cache_hit=cache_hit,
        needs_review=summary.confidence < _NEEDS_REVIEW_THRESHOLD,
        elapsed_ms=int((utcnow() - started).total_seconds() * 1000),
    )

    return SummarizeOutcome(
        email_id=inputs.email_id,
        ok=True,
        confidence=summary.confidence,
        tokens_in=response.call_result.tokens_in,
        tokens_out=response.call_result.tokens_out,
        cost_usd=response.call_result.cost_usd,
        cache_hit=cache_hit,
        fallback_used=response.fallback_used,
    )


def _render_body_md(summary: EmailSummary) -> str:
    """Render the summary into the markdown the UI consumes.

    Args:
        summary: Validated :class:`EmailSummary`.

    Returns:
        Markdown string — TL;DR paragraph, then optional key-points
        list, then optional action items.
    """
    parts: list[str] = [summary.tldr]
    if summary.key_points:
        parts.append("")
        parts.append("**Key points**")
        parts.extend(f"- {item}" for item in summary.key_points)
    if summary.action_items:
        parts.append("")
        parts.append("**Action items**")
        parts.extend(f"- [ ] {item}" for item in summary.action_items)
    return "\n".join(parts).strip()


async def _load_classification(
    session: AsyncSession,
    *,
    email_id: UUID,
) -> Classification | None:
    """Fetch the classification row for ``email_id`` if any."""
    from sqlalchemy import select  # noqa: PLC0415 — keep module import light

    return (
        (
            await session.execute(
                select(Classification).where(Classification.email_id == email_id),
            )
        )
        .scalars()
        .first()
    )


async def _has_email_summary(
    session: AsyncSession,
    *,
    email_id: UUID,
) -> bool:
    """Return True when a per-email summary already exists."""
    from sqlalchemy import select  # noqa: PLC0415 — keep module import light

    existing = await session.execute(
        select(Summary.id).where(
            Summary.kind == "email",
            Summary.email_id == email_id,
        ),
    )
    return existing.scalar_one_or_none() is not None


def _excerpt_for(
    row: Email,
    *,
    user_id: UUID,
    cipher: EnvelopeCipher | None,
) -> str:
    """Return the best plaintext excerpt for the prompt."""
    blob: EmailContentBlob | None = row.body
    excerpt = decrypt_excerpt(blob, user_id=user_id, cipher=cipher)
    if excerpt:
        return excerpt
    return row.snippet or ""


async def _persist_call_log(
    *,
    session: AsyncSession,
    record: PromptCallRecord,
    run_id: UUID | None,
) -> None:
    """Insert one :class:`PromptCallLog` row from a client record."""
    session.add(
        PromptCallLog(
            prompt_version_id=record.prompt_version_id,
            email_id=record.email_id,
            model=record.model,
            tokens_in=record.tokens_in,
            tokens_out=record.tokens_out,
            tokens_cache_read=record.tokens_cache_read,
            tokens_cache_write=record.tokens_cache_write,
            cost_usd=record.cost_usd,
            latency_ms=record.latency_ms,
            status=record.status,
            provider=record.provider,
            run_id=run_id,
            redaction_summary=record.redaction_counts,
        ),
    )
    await session.flush()


def _to_decimal(value: float) -> Decimal:
    """Convert a confidence float to a quantized Decimal (3 dp)."""
    return Decimal(str(value)).quantize(Decimal("0.001"))


__all__ = ["SummarizeInputs", "SummarizeOutcome", "summarize_email"]
