"""Run-scoped category digest summarization.

Phase 4 builds one synthesized digest per non-empty summarizable
category after the run's classifications and per-email summaries have
fully drained. The service reads only the explicit
``digest_run_emails`` membership set, so the prompt cannot see a partial
or timestamp-inferred run boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.sql import Executable

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import (
    Classification,
    ConnectedAccount,
    DigestRunEmail,
    Email,
    PromptCallLog,
    Summary,
)
from app.llm.client import LLMClient, LLMClientError, PromptCallRecord, render_prompt
from app.llm.schemas import CategoryDigestCategory, CategoryDigestSummary
from app.services.email_labels import unread_email_filter
from app.services.summarization.repository import SummariesRepo, SummaryCategoryDigestWrite

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.prompts.registry import RegisteredPrompt


logger = get_logger(__name__)


class CategoryDigestNotReadyError(RuntimeError):
    """Raised when a category digest would be built from a partial set."""


class CategoryDigestItem(BaseModel):
    """One per-email summary item supplied to the category prompt.

    Attributes:
        ref: Opaque stable item reference for source citation.
        subject: Source email subject.
        sender: Source email sender.
        tldr: Per-email TL;DR produced by the summarize prompt.
        key_points: Per-email key points produced by the summarize prompt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: str = Field(..., min_length=1, max_length=16, description="Opaque source ref.")
    subject: str = Field(..., max_length=240, description="Source email subject.")
    sender: str = Field(..., max_length=320, description="Source email sender.")
    tldr: str = Field(..., min_length=1, max_length=500, description="Per-email TL;DR.")
    key_points: tuple[str, ...] = Field(
        default=(),
        max_length=5,
        description="Per-email key points.",
    )

    @field_validator("ref", "subject", "sender", "tldr")
    @classmethod
    def _strip_scalar(cls, value: str) -> str:
        """Trim surrounding whitespace on scalar fields."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("category digest item fields must be non-empty")
        return stripped

    @field_validator("key_points")
    @classmethod
    def _strip_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Drop empty key points and trim whitespace."""
        return tuple(item.strip() for item in value if item and item.strip())


@dataclass(frozen=True)
class CategoryDigestInputs:
    """Everything needed to summarize one run/category pair.

    Attributes:
        user_id: Owner — bound into summary encryption context.
        run_id: Digest run to summarize.
        category: Triage category to summarize.
        prompt: Loaded ``category_digest`` prompt.
        prompt_version_id: ``prompt_versions.id`` matching ``prompt``.
        llm: Configured :class:`LLMClient`.
        repo: Encrypt-on-write :class:`SummariesRepo`.
    """

    user_id: UUID
    run_id: UUID
    category: CategoryDigestCategory
    prompt: RegisteredPrompt
    prompt_version_id: UUID
    llm: LLMClient
    repo: SummariesRepo


@dataclass(frozen=True)
class CategoryDigestOutcome:
    """Result returned to the worker handler.

    Attributes:
        run_id: Digest run id.
        category: Category summarized.
        ok: True when a digest row was written.
        confidence: Parsed model confidence; ``0.0`` on skip/failure.
        tokens_in: Tokens billed on input.
        tokens_out: Tokens billed on output.
        cost_usd: Provider cost for the call.
        cache_hit: Whether the provider reported cache-read tokens.
        fallback_used: True when a fallback model produced the digest.
        skipped_reason: Populated when ``ok=False``.
    """

    run_id: UUID
    category: CategoryDigestCategory
    ok: bool
    confidence: float
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    cache_hit: bool
    fallback_used: bool
    skipped_reason: str = ""


async def summarize_category(
    inputs: CategoryDigestInputs,
    *,
    session: AsyncSession,
) -> CategoryDigestOutcome:
    """Summarize one complete run/category set.

    Args:
        inputs: Collaborator bundle.
        session: Active async session (caller owns commit).

    Returns:
        :class:`CategoryDigestOutcome`.

    Raises:
        CategoryDigestNotReadyError: If classifications or per-email
            summaries have not fully drained for the category.
    """
    if await _has_category_digest(
        session=session,
        run_id=inputs.run_id,
        category=inputs.category,
    ):
        return _skipped(inputs, reason="already summarized")

    await _assert_complete_category(
        session=session,
        user_id=inputs.user_id,
        run_id=inputs.run_id,
        category=inputs.category,
    )
    items = await _load_category_items(
        session=session,
        user_id=inputs.user_id,
        run_id=inputs.run_id,
        category=inputs.category,
        repo=inputs.repo,
    )
    if not items:
        return _skipped(inputs, reason="empty category")

    rendered = render_prompt(
        inputs.prompt.spec,
        variables={
            "run_id": inputs.run_id,
            "category": inputs.category,
            "items_json": json.dumps(
                [item.model_dump(mode="json") for item in items],
                separators=(",", ":"),
            ),
        },
    )

    async def _log_call(record: PromptCallRecord) -> None:
        await _persist_call_log(session=session, record=record, run_id=inputs.run_id)

    started = utcnow()
    try:
        response = await inputs.llm.call(
            spec=inputs.prompt.spec,
            rendered_prompt=rendered,
            schema=CategoryDigestSummary,
            prompt_version_id=inputs.prompt_version_id,
            email_id=None,
            run_id=inputs.run_id,
            log_call=_log_call,
        )
    except LLMClientError as exc:
        logger.warning(
            "summarize.category.llm_failed",
            run_id=str(inputs.run_id),
            category=inputs.category,
            error=str(exc),
        )
        return _skipped(inputs, reason=str(exc))

    summary = response.parsed
    assert isinstance(summary, CategoryDigestSummary)
    cache_hit = response.call_result.tokens_cache_read > 0
    await inputs.repo.upsert_category_digest(
        session,
        SummaryCategoryDigestWrite(
            run_id=inputs.run_id,
            category=inputs.category,
            user_id=inputs.user_id,
            prompt_version_id=inputs.prompt_version_id,
            model=response.call_result.model,
            tokens_in=response.call_result.tokens_in,
            tokens_out=response.call_result.tokens_out,
            narrative=summary.narrative,
            groups=summary.groups,
            confidence=_to_decimal(summary.confidence),
            cache_hit=cache_hit,
        ),
    )

    logger.info(
        "summarize.category.completed",
        run_id=str(inputs.run_id),
        category=inputs.category,
        items=len(items),
        confidence=summary.confidence,
        tokens_in=response.call_result.tokens_in,
        tokens_out=response.call_result.tokens_out,
        cache_hit=cache_hit,
        fallback_used=response.fallback_used,
        elapsed_ms=int((utcnow() - started).total_seconds() * 1000),
    )
    return CategoryDigestOutcome(
        run_id=inputs.run_id,
        category=inputs.category,
        ok=True,
        confidence=summary.confidence,
        tokens_in=response.call_result.tokens_in,
        tokens_out=response.call_result.tokens_out,
        cost_usd=response.call_result.cost_usd,
        cache_hit=cache_hit,
        fallback_used=response.fallback_used,
    )


async def _has_category_digest(
    *,
    session: AsyncSession,
    run_id: UUID,
    category: CategoryDigestCategory,
) -> bool:
    """Return True when the run/category digest row already exists."""
    row = await session.execute(
        select(Summary.id)
        .where(
            Summary.kind == "category_digest",
            Summary.run_id == run_id,
            Summary.category == category,
        )
        .limit(1),
    )
    return row.scalar_one_or_none() is not None


async def _assert_complete_category(
    *,
    session: AsyncSession,
    user_id: UUID,
    run_id: UUID,
    category: CategoryDigestCategory,
) -> None:
    """Raise if a category digest would be built from a partial run."""
    pending_unclassified = await _count(
        session,
        select(func.count(DigestRunEmail.email_id))
        .join(Email, Email.id == DigestRunEmail.email_id)
        .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
        .outerjoin(Classification, Classification.email_id == Email.id)
        .where(
            DigestRunEmail.run_id == run_id,
            ConnectedAccount.user_id == user_id,
            unread_email_filter(session),
            Classification.email_id.is_(None),
        ),
    )
    if pending_unclassified:
        raise CategoryDigestNotReadyError("run has unclassified member emails")

    pending_summaries = await _count(
        session,
        select(func.count(DigestRunEmail.email_id))
        .join(Email, Email.id == DigestRunEmail.email_id)
        .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(
            Summary,
            and_(
                Summary.email_id == Email.id,
                Summary.kind == "email",
            ),
        )
        .where(
            DigestRunEmail.run_id == run_id,
            ConnectedAccount.user_id == user_id,
            unread_email_filter(session),
            Classification.label == category,
            Summary.email_id.is_(None),
        ),
    )
    if pending_summaries:
        raise CategoryDigestNotReadyError("category has unsummarized member emails")


async def _load_category_items(
    *,
    session: AsyncSession,
    user_id: UUID,
    run_id: UUID,
    category: CategoryDigestCategory,
    repo: SummariesRepo,
) -> tuple[CategoryDigestItem, ...]:
    """Load complete per-email summaries for one run/category."""
    rows = (
        await session.execute(
            select(Email, Summary)
            .join(DigestRunEmail, DigestRunEmail.email_id == Email.id)
            .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
            .join(Classification, Classification.email_id == Email.id)
            .join(Summary, Summary.email_id == Email.id)
            .where(
                DigestRunEmail.run_id == run_id,
                ConnectedAccount.user_id == user_id,
                unread_email_filter(session),
                Classification.label == category,
                Summary.kind == "email",
            )
            .order_by(Email.internal_date.desc(), Email.id.desc()),
        )
    ).all()

    items: list[CategoryDigestItem] = []
    for index, (email_row, summary_row) in enumerate(rows, start=1):
        body = repo.decrypt_email_body(row=summary_row, user_id=user_id)
        tldr, key_points = _summary_parts(body)
        items.append(
            CategoryDigestItem(
                ref=f"E{index}",
                subject=email_row.subject or "(no subject)",
                sender=email_row.from_addr,
                tldr=tldr or email_row.snippet or email_row.subject or "(summary unavailable)",
                key_points=key_points,
            ),
        )
    return tuple(items)


def _summary_parts(body: str) -> tuple[str, tuple[str, ...]]:
    """Extract the TL;DR and key points from per-email summary markdown."""
    lines = [line.strip() for line in body.splitlines()]
    non_empty = [line for line in lines if line]
    if not non_empty:
        return "", ()

    tldr = non_empty[0]
    key_points: list[str] = []
    in_key_points = False
    for line in non_empty[1:]:
        if line == "**Key points**":
            in_key_points = True
            continue
        if line.startswith("**") and line.endswith("**"):
            in_key_points = False
        if in_key_points and line.startswith("- "):
            key_points.append(line[2:].strip())
    return tldr, tuple(key_points[:5])


async def _persist_call_log(
    *,
    session: AsyncSession,
    record: PromptCallRecord,
    run_id: UUID,
) -> None:
    """Insert one :class:`PromptCallLog` row from a client record."""
    session.add(
        PromptCallLog(
            prompt_version_id=record.prompt_version_id,
            email_id=None,
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


async def _count(session: AsyncSession, statement: Executable) -> int:
    """Execute a scalar count statement and return an ``int``."""
    return int((await session.execute(statement)).scalar_one() or 0)


def _skipped(inputs: CategoryDigestInputs, *, reason: str) -> CategoryDigestOutcome:
    """Return a zeroed skipped outcome for ``inputs``."""
    return CategoryDigestOutcome(
        run_id=inputs.run_id,
        category=inputs.category,
        ok=False,
        confidence=0.0,
        tokens_in=0,
        tokens_out=0,
        cost_usd=Decimal("0"),
        cache_hit=False,
        fallback_used=False,
        skipped_reason=reason,
    )


def _to_decimal(value: float) -> Decimal:
    """Convert a confidence float to a quantized Decimal (3 dp)."""
    return Decimal(str(value)).quantize(Decimal("0.001"))


__all__ = [
    "CategoryDigestInputs",
    "CategoryDigestItem",
    "CategoryDigestNotReadyError",
    "CategoryDigestOutcome",
    "summarize_category",
]
