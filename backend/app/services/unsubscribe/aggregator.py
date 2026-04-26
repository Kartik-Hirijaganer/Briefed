"""SQL aggregate + borderline LLM orchestrator (plan §14 Phase 5, §7).

The hygiene pipeline runs per connected-account and produces one
:class:`app.db.models.UnsubscribeSuggestion` per ``(account, sender)``:

1. :func:`aggregate_sender_stats` groups
   :class:`app.db.models.Email` x :class:`app.db.models.Classification`
   over the trailing 30 days by ``from_addr`` and computes
   :class:`SenderStats`.
2. :func:`score_sender` maps those stats onto three binary rule
   criteria — **noisy** (volume), **low_value** (waste rate),
   **disengaged** (engagement score). All three → auto-recommend
   with ``confidence=0.9`` (rule-only). Exactly two → borderline;
   the LLM makes the final call. One or zero → skip.
3. :func:`rank_senders` runs the aggregate, calls the LLM on
   borderline candidates through :class:`app.llm.client.LLMClient`,
   and upserts rows via
   :class:`app.services.unsubscribe.repository.UnsubscribeSuggestionsRepo`.

Confidence policy (plan §7): rows at or below 0.8 never auto-act;
release 1.0.0 never auto-acts anyway, so this is enforced at the UI
layer. Rows with ``dismissed=True`` are preserved across runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, select

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import (
    Classification,
    ConnectedAccount,
    Email,
    PromptCallLog,
    PromptVersion,
)
from app.llm.client import LLMClient, LLMClientError, PromptCallRecord, render_prompt
from app.llm.schemas import UnsubscribeDecision
from app.services.unsubscribe.parser import (
    UnsubscribeAction,
    parse_list_unsubscribe,
)
from app.services.unsubscribe.repository import (
    UnsubscribeSuggestionsRepo,
    UnsubscribeSuggestionWrite,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.prompts.registry import RegisteredPrompt


logger = get_logger(__name__)

_LOOKBACK_DAYS = 30
"""Plan §7 — sender x 30-day window for the hygiene aggregate."""

_VOLUME_THRESHOLD = 5
"""Criterion ``noisy`` — frequency ≥ this is high-volume."""

_WASTE_THRESHOLD = Decimal("0.50")
"""Criterion ``low_value`` — waste rate ≥ this is wasteful."""

_ENGAGEMENT_CEILING = Decimal("0.20")
"""Criterion ``disengaged`` — engagement at or below this is cold."""

_RULE_ONLY_CONFIDENCE = Decimal("0.900")
"""Confidence stamped when all three criteria hit (no LLM call)."""

_POLICY_GATE_MIN = Decimal("0.200")
"""Minimum confidence persisted when the LLM vetoes. Keeps the row
visible for audit without surfacing as a recommendation.
"""

_SUBJECT_SAMPLE_COUNT = 6
"""Recent subjects shown to the LLM on borderline calls."""

_MAX_SUBJECT_LEN = 160
"""Truncate individual subjects so the prompt fits in cache tiers."""

_POSITIVE_LABELS: frozenset[str] = frozenset(
    {"must_read", "good_to_read", "job_candidate"},
)
"""Primary and legacy labels that count toward engagement."""

_WASTE_LABELS: frozenset[str] = frozenset({"waste", "ignore"})
"""Labels that count toward waste rate."""


@dataclass(frozen=True)
class SenderStats:
    """One row of the 30-day sender aggregate.

    Attributes:
        sender_email: Normalized full address, lowercased.
        sender_domain: Domain portion of :attr:`sender_email`.
        frequency_30d: Total email count in the window.
        positive_count: Classifications with a positive label.
        waste_count: Classifications with a waste/ignore label.
        classified_total: Total classified rows — denominator for the
            engagement + waste ratios. May be less than
            :attr:`frequency_30d` when some emails are still
            unclassified.
        engagement_score: ``positive_count / classified_total``
            (``Decimal(0.000)`` when the denominator is zero).
        waste_rate: ``waste_count / classified_total`` (``Decimal(0.000)``
            when denominator is zero).
        list_unsubscribe: Normalized :class:`UnsubscribeAction` for the
            most recent email that carried a ``List-Unsubscribe``
            header. ``None`` when no email in the window had one.
        last_email_at: Most recent ``internal_date`` from this sender.
        recent_subjects: Up to :data:`_SUBJECT_SAMPLE_COUNT` subjects
            lifted from the window (newest first), each truncated to
            :data:`_MAX_SUBJECT_LEN` characters.
    """

    sender_email: str
    sender_domain: str
    frequency_30d: int
    positive_count: int
    waste_count: int
    classified_total: int
    engagement_score: Decimal
    waste_rate: Decimal
    list_unsubscribe: UnsubscribeAction | None
    last_email_at: datetime | None
    recent_subjects: tuple[str, ...]


@dataclass(frozen=True)
class CriteriaScore:
    """Boolean rule-engine signals derived from :class:`SenderStats`.

    Attributes:
        noisy: ``frequency_30d >= _VOLUME_THRESHOLD``.
        low_value: ``waste_rate >= _WASTE_THRESHOLD``.
        disengaged: ``engagement_score <= _ENGAGEMENT_CEILING``.
        hit_count: Number of ``True`` flags — drives the rule gate.
    """

    noisy: bool
    low_value: bool
    disengaged: bool
    hit_count: int

    @property
    def labels(self) -> tuple[str, ...]:
        """Return the criterion names that fired, in a stable order."""
        tags: list[str] = []
        if self.noisy:
            tags.append("noisy")
        if self.low_value:
            tags.append("low_value")
        if self.disengaged:
            tags.append("disengaged")
        return tuple(tags)


@dataclass(frozen=True)
class RankOutcome:
    """Result of :func:`rank_senders` — useful for observability.

    Attributes:
        candidates: Total senders the aggregate scored.
        rule_recommendations: Count persisted by the rule-only branch.
        model_recommendations: Count persisted by the LLM branch.
        skipped: Count of candidates where the criteria did not fire
            twice — no row written.
        llm_errors: Count of borderline candidates where the LLM call
            failed and no row was written.
    """

    candidates: int
    rule_recommendations: int
    model_recommendations: int
    skipped: int
    llm_errors: int


async def aggregate_sender_stats(
    *,
    session: AsyncSession,
    account_id: UUID,
    now: datetime | None = None,
    lookback_days: int = _LOOKBACK_DAYS,
) -> list[SenderStats]:
    """Compute sender-level aggregates over the trailing ``lookback_days``.

    Args:
        session: Active async session.
        account_id: Target connected account.
        now: UTC anchor for the lookback window. Defaults to
            :func:`app.core.clock.utcnow`.
        lookback_days: Window size in days. Exposed for tests; the
            production value is :data:`_LOOKBACK_DAYS`.

    Returns:
        One :class:`SenderStats` per distinct sender, ordered by
        ``sender_email`` for determinism in tests.
    """
    anchor = now if now is not None else utcnow()
    cutoff = anchor - timedelta(days=lookback_days)

    email_window = and_(
        Email.account_id == account_id,
        Email.internal_date >= cutoff,
    )

    rows = (
        await session.execute(
            select(Email.id, Email.from_addr, Email.subject, Email.internal_date)
            .where(email_window)
            .order_by(Email.from_addr, Email.internal_date.desc()),
        )
    ).all()

    class_rows = (
        await session.execute(
            select(
                Classification.email_id,
                Classification.label,
                Classification.is_job_candidate,
            )
            .join(Email, Email.id == Classification.email_id)
            .where(email_window),
        )
    ).all()
    labels_by_email: dict[UUID, tuple[str, bool]] = {
        row.email_id: (row.label, row.is_job_candidate) for row in class_rows
    }

    unsub_rows = (
        await session.execute(
            select(Email.from_addr, Email.list_unsubscribe, Email.internal_date)
            .where(
                email_window,
                Email.list_unsubscribe.is_not(None),
            )
            .order_by(Email.from_addr, Email.internal_date.desc()),
        )
    ).all()
    latest_unsub: dict[str, UnsubscribeAction] = {}
    for row in unsub_rows:
        sender = _normalize_sender(row.from_addr)
        if sender in latest_unsub:
            continue
        unsub_action = _unsub_from_stored(row.list_unsubscribe)
        if unsub_action is not None:
            latest_unsub[sender] = unsub_action

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        sender = _normalize_sender(row.from_addr)
        bucket = grouped.setdefault(
            sender,
            {
                "frequency": 0,
                "positive": 0,
                "waste": 0,
                "classified": 0,
                "last_at": row.internal_date,
                "subjects": [],
            },
        )
        bucket["frequency"] += 1
        if bucket["last_at"] is None or row.internal_date > bucket["last_at"]:
            bucket["last_at"] = row.internal_date
        if len(bucket["subjects"]) < _SUBJECT_SAMPLE_COUNT:
            bucket["subjects"].append(_sanitize_subject(row.subject))
        label_info = labels_by_email.get(row.id)
        if label_info is not None:
            label, is_job_candidate = label_info
            bucket["classified"] += 1
            if label in _POSITIVE_LABELS or is_job_candidate:
                bucket["positive"] += 1
            elif label in _WASTE_LABELS:
                bucket["waste"] += 1

    stats: list[SenderStats] = []
    for sender, bucket in grouped.items():
        total = int(bucket["classified"])
        positive = int(bucket["positive"])
        waste = int(bucket["waste"])
        engagement = Decimal(positive) / Decimal(total) if total else Decimal("0")
        waste_rate = Decimal(waste) / Decimal(total) if total else Decimal("0")
        stats.append(
            SenderStats(
                sender_email=sender,
                sender_domain=_domain_of(sender),
                frequency_30d=int(bucket["frequency"]),
                positive_count=positive,
                waste_count=waste,
                classified_total=total,
                engagement_score=_quantize(engagement),
                waste_rate=_quantize(waste_rate),
                list_unsubscribe=latest_unsub.get(sender),
                last_email_at=bucket["last_at"],
                recent_subjects=tuple(bucket["subjects"]),
            ),
        )

    stats.sort(key=lambda s: s.sender_email)
    return stats


def score_sender(stats: SenderStats) -> CriteriaScore:
    """Map :class:`SenderStats` onto the three rule criteria.

    Args:
        stats: Aggregate row.

    Returns:
        :class:`CriteriaScore` with a ``hit_count`` in ``[0, 3]``.
    """
    noisy = stats.frequency_30d >= _VOLUME_THRESHOLD
    low_value = stats.waste_rate >= _WASTE_THRESHOLD
    disengaged = stats.classified_total > 0 and stats.engagement_score <= _ENGAGEMENT_CEILING
    hits = sum(1 for flag in (noisy, low_value, disengaged) if flag)
    return CriteriaScore(
        noisy=noisy,
        low_value=low_value,
        disengaged=disengaged,
        hit_count=hits,
    )


async def rank_senders(
    *,
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    llm: LLMClient,
    prompt: RegisteredPrompt,
    prompt_version_id: UUID,
    repo: UnsubscribeSuggestionsRepo,
    run_id: UUID | None = None,
    now: datetime | None = None,
) -> RankOutcome:
    """Aggregate, score, and persist unsubscribe suggestions.

    Args:
        session: Active async session (caller owns commit).
        user_id: Owner — bound into the encryption context.
        account_id: Target connected account.
        llm: Configured :class:`LLMClient` for borderline calls.
        prompt: Loaded :class:`RegisteredPrompt` for
            ``unsubscribe_borderline``.
        prompt_version_id: ``prompt_versions.id`` matching ``prompt``.
        repo: Encrypt-on-write :class:`UnsubscribeSuggestionsRepo`.
        run_id: Optional digest-run scope for the prompt-call-log row.
        now: UTC anchor for the aggregate window.

    Returns:
        :class:`RankOutcome` with per-branch counters.

    Raises:
        LookupError: When the ``connected_accounts`` row is missing.
    """
    account = await session.get(ConnectedAccount, account_id)
    if account is None:
        raise LookupError(f"connected_account {account_id} not found")

    stats = await aggregate_sender_stats(
        session=session,
        account_id=account_id,
        now=now,
    )

    rule_count = 0
    model_count = 0
    skipped = 0
    llm_errors = 0

    for row in stats:
        score = score_sender(row)
        if score.hit_count < 2:
            skipped += 1
            continue

        if score.hit_count == 3:
            await _persist(
                session=session,
                repo=repo,
                stats=row,
                user_id=user_id,
                account_id=account_id,
                confidence=_RULE_ONLY_CONFIDENCE,
                decision_source="rule",
                rationale=_rule_rationale(row, score),
                prompt_version_id=None,
                model="",
                tokens_in=0,
                tokens_out=0,
            )
            rule_count += 1
            continue

        outcome = await _call_borderline_llm(
            stats=row,
            score=score,
            llm=llm,
            prompt=prompt,
            prompt_version_id=prompt_version_id,
            session=session,
            run_id=run_id,
        )
        if outcome is None:
            llm_errors += 1
            continue

        decision, call_result = outcome
        confidence = Decimal(str(decision.confidence))
        if not decision.should_recommend:
            # Persist the audit row but cap the confidence so it never
            # bubbles up as a recommendation.
            confidence = min(confidence, _POLICY_GATE_MIN)
        await _persist(
            session=session,
            repo=repo,
            stats=row,
            user_id=user_id,
            account_id=account_id,
            confidence=_quantize(confidence),
            decision_source="model",
            rationale=decision.rationale,
            prompt_version_id=prompt_version_id,
            model=call_result.model,
            tokens_in=call_result.tokens_in,
            tokens_out=call_result.tokens_out,
        )
        model_count += 1

    logger.info(
        "unsubscribe.rank.completed",
        account_id=str(account_id),
        candidates=len(stats),
        rule=rule_count,
        model=model_count,
        skipped=skipped,
        llm_errors=llm_errors,
    )
    return RankOutcome(
        candidates=len(stats),
        rule_recommendations=rule_count,
        model_recommendations=model_count,
        skipped=skipped,
        llm_errors=llm_errors,
    )


async def _persist(
    *,
    session: AsyncSession,
    repo: UnsubscribeSuggestionsRepo,
    stats: SenderStats,
    user_id: UUID,
    account_id: UUID,
    confidence: Decimal,
    decision_source: str,
    rationale: str,
    prompt_version_id: UUID | None,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Upsert one row via ``repo``. Wrapper for readability."""
    await repo.upsert(
        session,
        UnsubscribeSuggestionWrite(
            account_id=account_id,
            user_id=user_id,
            sender_domain=stats.sender_domain,
            sender_email=stats.sender_email,
            frequency_30d=stats.frequency_30d,
            engagement_score=stats.engagement_score,
            waste_rate=stats.waste_rate,
            list_unsubscribe=(
                stats.list_unsubscribe.model_dump() if stats.list_unsubscribe is not None else None
            ),
            confidence=confidence,
            decision_source=decision_source,
            rationale=rationale,
            prompt_version_id=prompt_version_id,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            last_email_at=stats.last_email_at,
        ),
    )


async def _call_borderline_llm(
    *,
    stats: SenderStats,
    score: CriteriaScore,
    llm: LLMClient,
    prompt: RegisteredPrompt,
    prompt_version_id: UUID,
    session: AsyncSession,
    run_id: UUID | None,
) -> tuple[UnsubscribeDecision, Any] | None:
    """Invoke ``LLMClient`` for a borderline sender; persist the call log.

    Returns:
        ``(decision, call_result)`` on success; ``None`` when every
        provider in the chain failed.
    """
    rendered = render_prompt(
        prompt.spec,
        variables={
            "sender_email": stats.sender_email,
            "sender_domain": stats.sender_domain,
            "frequency_30d": str(stats.frequency_30d),
            "engagement_score": _format_ratio(stats.engagement_score),
            "waste_rate": _format_ratio(stats.waste_rate),
            "has_list_unsubscribe": "true" if stats.list_unsubscribe else "false",
            "criteria_hit": ",".join(score.labels) or "none",
            "subject_samples": _format_subjects(stats.recent_subjects),
        },
    )

    async def _log_call(record: PromptCallRecord) -> None:
        await _persist_call_log(session=session, record=record, run_id=run_id)

    try:
        response = await llm.call(
            spec=prompt.spec,
            rendered_prompt=rendered,
            schema=UnsubscribeDecision,
            prompt_version_id=prompt_version_id,
            email_id=None,
            run_id=run_id,
            log_call=_log_call,
        )
    except LLMClientError as exc:
        logger.warning(
            "unsubscribe.llm_failed",
            sender_email=stats.sender_email,
            error=str(exc),
        )
        return None

    parsed = response.parsed
    assert isinstance(parsed, UnsubscribeDecision)
    return parsed, response.call_result


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


async def load_prompt_version_row(
    *,
    session: AsyncSession,
    content_hash: bytes,
) -> PromptVersion:
    """Resolve the ``prompt_versions`` row for ``content_hash``.

    Args:
        session: Active async session.
        content_hash: SHA-256 digest from the prompt registry.

    Returns:
        Attached :class:`PromptVersion`.

    Raises:
        LookupError: When no row exists for the digest (handler
            surfaces this to SQS, which re-delivers).
    """
    row = (
        (
            await session.execute(
                select(PromptVersion).where(PromptVersion.content_hash == content_hash),
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise LookupError("unsubscribe_borderline prompt_versions row missing")
    return row


def _rule_rationale(stats: SenderStats, score: CriteriaScore) -> str:
    """Deterministic rationale string for rule-only (3-of-3) rows.

    The rationale is stored encrypted at rest; it is meant to be
    human-readable in the UI and cite the signals so the user can
    trust the recommendation without an LLM roundtrip.
    """
    engagement_pct = int(stats.engagement_score * 100)
    waste_pct = int(stats.waste_rate * 100)
    return (
        f"{stats.frequency_30d} emails in the last 30 days,"
        f" {engagement_pct}% engagement, {waste_pct}% wasted — all three"
        f" unsubscribe criteria triggered ({', '.join(score.labels)})."
    )


def _sanitize_subject(subject: str) -> str:
    """Truncate + strip a subject line for LLM consumption."""
    stripped = subject.strip().replace("\n", " ").replace("\r", " ")
    return stripped[:_MAX_SUBJECT_LEN]


def _normalize_sender(raw: str) -> str:
    """Lowercase + trim a sender address so aggregates group correctly."""
    return raw.strip().lower()


def _domain_of(sender_email: str) -> str:
    """Return the domain suffix of ``sender_email`` (after the last ``@``)."""
    _, _, domain = sender_email.rpartition("@")
    return domain or sender_email


def _unsub_from_stored(value: object) -> UnsubscribeAction | None:
    """Rebuild :class:`UnsubscribeAction` from a JSON column value.

    ``emails.list_unsubscribe`` is stored either as a JSON dict
    (legacy — direct ``UnsubscribeInfo.model_dump()``) or as a raw
    header string (future-proofing for non-Gmail providers). Both
    shapes collapse through :func:`parse_list_unsubscribe` so the
    downstream code only sees one type.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        http_urls = value.get("http_urls") or ()
        mailto = value.get("mailto")
        one_click = bool(value.get("one_click", False))
        urls = tuple(str(url) for url in http_urls) if isinstance(http_urls, list | tuple) else ()
        if not urls and not mailto:
            return None
        return UnsubscribeAction(
            http_urls=urls,
            mailto=str(mailto) if mailto else None,
            one_click=one_click,
        )
    if isinstance(value, str):
        return parse_list_unsubscribe(value)
    return None


def _format_ratio(value: Decimal) -> str:
    """Format a ratio Decimal as a ``0.XX`` string for the prompt."""
    return f"{float(value):.2f}"


def _format_subjects(subjects: tuple[str, ...]) -> str:
    """Render a sample list as a markdown-ish bullet block."""
    if not subjects:
        return "(no subjects in window)"
    return "\n".join(f'- "{subject}"' for subject in subjects)


def _quantize(value: Decimal) -> Decimal:
    """Quantize a ratio Decimal to three decimal places (column scale)."""
    value = max(value, Decimal("0"))
    value = min(value, Decimal("1"))
    return value.quantize(Decimal("0.001"))


__all__ = [
    "CriteriaScore",
    "RankOutcome",
    "SenderStats",
    "aggregate_sender_stats",
    "load_prompt_version_row",
    "rank_senders",
    "score_sender",
]
