"""Per-email job extractor (plan §14 Phase 4).

Given one :class:`app.db.models.Email` that classification tagged as
``job_candidate``, this module:

1. Renders the ``job_extract`` prompt from the registry.
2. Calls :class:`app.llm.client.LLMClient`. The client's provider chain
   + circuit breaker drive retries; this module stays single-purpose.
3. Validates the :class:`app.llm.schemas.JobMatch` payload.
4. **Corroborates** any salary numbers against the source body — if
   ``comp_phrase`` does not re-match the email text, the comp fields
   are zeroed out before persistence. Confidence is suppressed below
   the 0.7 digest floor so the row does not surface as a match.
5. Loads the user's active :class:`app.db.models.JobFilter` rows and
   evaluates each predicate in :mod:`app.services.jobs.predicate`.
6. Writes a :class:`app.db.models.JobMatch` row via
   :class:`app.services.jobs.repository.JobMatchesRepo`
   (``match_reason`` envelope-encrypted).
7. Appends a :class:`app.db.models.PromptCallLog` row (cost + cache
   telemetry).

Confidence < 0.7 still writes the row so the triage UI can show a
"low-confidence" badge; the digest composer suppresses the row from
the jobs board by reading ``passed_filter=True AND match_score >= 0.7``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import (
    Email,
    EmailContentBlob,
    JobFilter,
    PromptCallLog,
)
from app.db.models import (
    JobMatch as JobMatchRow,
)
from app.llm.client import LLMClient, LLMClientError, PromptCallRecord, render_prompt
from app.llm.schemas import JobMatch
from app.services.ingestion.content import decrypt_excerpt
from app.services.jobs.predicate import JobCandidate, evaluate_many
from app.services.jobs.repository import JobMatchesRepo, JobMatchWrite

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher
    from app.services.prompts.registry import RegisteredPrompt


logger = get_logger(__name__)

_PASSED_FILTER_CONFIDENCE_FLOOR = 0.7
"""Digest-visible rows must clear this (plan §14 Phase 4 exit criteria)."""

_DEFAULT_READER_PROFILE = (
    "Senior software engineer; cares about compensation clarity, remote"
    " flexibility, and seniority alignment. Prefers explicit salary"
    " ranges over vague placements."
)
"""Default reader context when the prompt has no preferences snapshot."""


class CorroborationError(Exception):
    """Raised internally when the salary guard must suppress a row."""


@dataclass(frozen=True)
class ExtractInputs:
    """Everything the pipeline needs to extract one job.

    Attributes:
        email_id: Target email.
        user_id: Owner — bound into the encryption context.
        prompt: Loaded :class:`RegisteredPrompt` for ``job_extract``.
        prompt_version_id: ``prompt_versions.id`` matching ``prompt``.
        llm: Configured :class:`LLMClient`.
        repo: Encrypt-on-write :class:`JobMatchesRepo`.
        reader_profile: Optional override of the default profile
            passed to the prompt.
        content_cipher: Optional content-at-rest cipher for body excerpts.
    """

    email_id: UUID
    user_id: UUID
    prompt: RegisteredPrompt
    prompt_version_id: UUID
    llm: LLMClient
    repo: JobMatchesRepo
    reader_profile: str | None = None
    content_cipher: EnvelopeCipher | None = None


@dataclass(frozen=True)
class ExtractOutcome:
    """Result returned to the worker handler.

    Attributes:
        email_id: Echoed back for convenience.
        ok: ``True`` when a row was written.
        passed_filter: Whether the extracted row cleared every active
            filter plus the confidence floor. Only meaningful when
            ``ok=True``.
        match_score: Calibrated confidence as float; ``0.0`` on failure.
        corroborated: ``True`` when the salary guard accepted the row
            as-is; ``False`` when the guard zeroed out comp fields
            because the body did not contain ``comp_phrase``. ``True``
            also when the model returned no comp to begin with.
        tokens_in: Tokens billed on input.
        tokens_out: Tokens billed on output.
        cost_usd: Summed cost of the extract call.
        cache_hit: Whether the provider reported cache-read tokens.
        fallback_used: True when the fallback adapter produced the row.
        skipped_reason: Populated when ``ok=False``.
    """

    email_id: UUID
    ok: bool
    passed_filter: bool
    match_score: float
    corroborated: bool
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    cache_hit: bool
    fallback_used: bool
    skipped_reason: str = ""


async def extract_job(
    inputs: ExtractInputs,
    *,
    session: AsyncSession,
    run_id: UUID | None = None,
) -> ExtractOutcome:
    """Extract one job posting end-to-end.

    Args:
        inputs: Collaborator bundle.
        session: Active async session (caller owns commit).
        run_id: Optional digest-run scope for the prompt-call-log row.

    Returns:
        :class:`ExtractOutcome`.

    Raises:
        LookupError: When the target email row has vanished.
    """
    email_row = await session.get(Email, inputs.email_id)
    if email_row is None:
        raise LookupError(f"email {inputs.email_id} not found")

    if await _has_job_match(session, email_id=inputs.email_id):
        return ExtractOutcome(
            email_id=inputs.email_id,
            ok=False,
            passed_filter=False,
            match_score=0.0,
            corroborated=True,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            cache_hit=False,
            fallback_used=False,
            skipped_reason="already extracted",
        )

    excerpt = _excerpt_for(
        email_row,
        user_id=inputs.user_id,
        cipher=inputs.content_cipher,
    )
    rendered = render_prompt(
        inputs.prompt.spec,
        variables={
            "from_addr": email_row.from_addr,
            "subject": email_row.subject,
            "plain_text_excerpt": excerpt,
            "reader_profile": inputs.reader_profile or _DEFAULT_READER_PROFILE,
        },
    )

    async def _log_call(record: PromptCallRecord) -> None:
        await _persist_call_log(session=session, record=record, run_id=run_id)

    started = utcnow()
    try:
        response = await inputs.llm.call(
            spec=inputs.prompt.spec,
            rendered_prompt=rendered,
            schema=JobMatch,
            prompt_version_id=inputs.prompt_version_id,
            email_id=inputs.email_id,
            run_id=run_id,
            log_call=_log_call,
        )
    except LLMClientError as exc:
        logger.warning(
            "jobs.extract.llm_failed",
            email_id=str(inputs.email_id),
            error=str(exc),
        )
        return ExtractOutcome(
            email_id=inputs.email_id,
            ok=False,
            passed_filter=False,
            match_score=0.0,
            corroborated=True,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            cache_hit=False,
            fallback_used=False,
            skipped_reason=str(exc),
        )

    extracted = response.parsed
    assert isinstance(extracted, JobMatch)

    corroborated_match, corroborated_ok = corroborate_comp(extracted, body=excerpt)
    effective_confidence = corroborated_match.confidence

    filters = await _load_active_filters(session, user_id=inputs.user_id)
    candidate = _candidate_from(corroborated_match)
    predicate_ok = evaluate_many([f.predicate for f in filters], candidate)
    confidence_ok = effective_confidence >= _PASSED_FILTER_CONFIDENCE_FLOOR
    passed_filter = predicate_ok and confidence_ok
    filter_version = _current_filter_version(filters)

    await inputs.repo.upsert(
        session,
        JobMatchWrite(
            email_id=inputs.email_id,
            user_id=inputs.user_id,
            title=corroborated_match.title,
            company=corroborated_match.company,
            location=corroborated_match.location,
            remote=corroborated_match.remote,
            comp_min=corroborated_match.comp_min,
            comp_max=corroborated_match.comp_max,
            currency=corroborated_match.currency,
            comp_phrase=corroborated_match.comp_phrase,
            seniority=corroborated_match.seniority,
            source_url=corroborated_match.source_url,
            match_score=_to_decimal(effective_confidence),
            filter_version=filter_version,
            passed_filter=passed_filter,
            prompt_version_id=inputs.prompt_version_id,
            model=response.call_result.model,
            tokens_in=response.call_result.tokens_in,
            tokens_out=response.call_result.tokens_out,
            match_reason=corroborated_match.match_reason,
        ),
    )

    cache_hit = response.call_result.tokens_cache_read > 0

    logger.info(
        "jobs.extract.completed",
        email_id=str(inputs.email_id),
        match_score=effective_confidence,
        passed_filter=passed_filter,
        corroborated=corroborated_ok,
        filters_applied=len(filters),
        filter_version=filter_version,
        cache_hit=cache_hit,
        elapsed_ms=int((utcnow() - started).total_seconds() * 1000),
    )

    return ExtractOutcome(
        email_id=inputs.email_id,
        ok=True,
        passed_filter=passed_filter,
        match_score=effective_confidence,
        corroborated=corroborated_ok,
        tokens_in=response.call_result.tokens_in,
        tokens_out=response.call_result.tokens_out,
        cost_usd=response.call_result.cost_usd,
        cache_hit=cache_hit,
        fallback_used=response.fallback_used,
    )


_SALARY_NUMERIC_RE = re.compile(r"\d")
"""Quick test: does ``comp_phrase`` carry numeric characters?"""


def corroborate_comp(match: JobMatch, *, body: str) -> tuple[JobMatch, bool]:
    """Regex-corroborate salary numbers against the source body.

    When the model returns ``comp_min``, ``comp_max``, ``currency``, or
    a numeric ``comp_phrase``, this function verifies the phrase (or
    each numeric token inside it) actually appears in ``body``. Rows
    that fail corroboration get their comp fields zeroed out and their
    confidence knocked below the digest floor so the hallucinated
    salary cannot ship.

    Returns:
        Tuple ``(match, ok)``. ``match`` is either the original object
        (when corroboration passed or the model returned no comp) or a
        sanitized copy. ``ok`` is ``True`` when no sanitization was
        required.
    """
    phrase_has_digit = (
        match.comp_phrase is not None and _SALARY_NUMERIC_RE.search(match.comp_phrase) is not None
    )
    has_numeric_comp = match.comp_min is not None or match.comp_max is not None or phrase_has_digit
    if not has_numeric_comp:
        return match, True
    if match.comp_phrase is None:
        return _sanitize(match), False

    if not _phrase_in_body(match.comp_phrase, body):
        logger.warning(
            "jobs.extract.corroboration_failed",
            comp_phrase=match.comp_phrase,
        )
        return _sanitize(match), False
    return match, True


def _phrase_in_body(phrase: str, body: str) -> bool:
    """Return ``True`` when every numeric token in ``phrase`` appears in ``body``.

    We do not insist the entire ``comp_phrase`` be a verbatim substring
    because the model is allowed to normalize whitespace / dashes. What
    we DO insist on is that every digit-run inside the phrase is
    present in the body — that guards against the model inventing
    numbers while still tolerating ``"$150,000 - $180,000"`` vs
    ``"$150,000-$180,000"`` style differences.
    """
    tokens = [tok for tok in re.findall(r"\d[\d,\.]*", phrase) if tok]
    if not tokens:
        # No numbers in the phrase despite has_numeric_comp being true
        # — treat as suspicious.
        return False
    body_digits = body.replace(",", "").replace(".", "")
    for token in tokens:
        normalized = token.replace(",", "").replace(".", "")
        if normalized not in body_digits:
            return False
    return True


def _sanitize(match: JobMatch) -> JobMatch:
    """Return a copy of ``match`` with comp fields zeroed + confidence capped."""
    capped = min(match.confidence, _PASSED_FILTER_CONFIDENCE_FLOOR - 0.01)
    return match.model_copy(
        update={
            "comp_min": None,
            "comp_max": None,
            "currency": None,
            "comp_phrase": None,
            "confidence": max(0.0, capped),
        },
    )


def _candidate_from(match: JobMatch) -> JobCandidate:
    """Build a :class:`JobCandidate` from a validated :class:`JobMatch`."""
    return JobCandidate(
        title=match.title,
        company=match.company,
        location=match.location,
        remote=match.remote,
        comp_min=match.comp_min,
        comp_max=match.comp_max,
        currency=match.currency,
        seniority=match.seniority,
        match_score=match.confidence,
    )


async def _load_active_filters(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> list[JobFilter]:
    """Return the active :class:`JobFilter` rows for ``user_id``.

    Filters are ordered by primary key so the logged version is stable
    across runs when the DB returns rows in insertion order.
    """
    rows = (
        (
            await session.execute(
                select(JobFilter)
                .where(JobFilter.user_id == user_id, JobFilter.active.is_(True))
                .order_by(JobFilter.created_at, JobFilter.id),
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _has_job_match(
    session: AsyncSession,
    *,
    email_id: UUID,
) -> bool:
    """Return True when this email already has an extracted job row."""
    existing = await session.execute(
        select(JobMatchRow.id).where(JobMatchRow.email_id == email_id),
    )
    return existing.scalar_one_or_none() is not None


def _current_filter_version(filters: list[JobFilter]) -> int:
    """Aggregate filter version — max across the active set.

    Using ``max`` (rather than a sum) means a single bumped filter
    rotates the stamped version while leaving untouched filters alone.
    Returns ``0`` when no filters are active, which mirrors the
    column default.
    """
    if not filters:
        return 0
    return max(int(f.version) for f in filters)


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
        ),
    )
    await session.flush()


def _to_decimal(value: float) -> Decimal:
    """Convert a confidence float to a quantized Decimal (3 dp)."""
    return Decimal(str(value)).quantize(Decimal("0.001"))


__all__ = [
    "CorroborationError",
    "ExtractInputs",
    "ExtractOutcome",
    "corroborate_comp",
    "extract_job",
]
