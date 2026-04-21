"""Classification orchestrator (plan §14 Phase 2).

Given one email row, this module:

1. Loads the rule snapshot via
   :func:`app.services.classification.rubric.load_default_rules`.
2. Runs the rule engine. High-confidence matches skip the LLM.
3. On miss (or low-confidence match) it calls :class:`app.llm.client.LLMClient`
   with the triage prompt.
4. Writes a :class:`app.db.models.Classification` row via
   :class:`ClassificationsRepo` (reasons envelope-encrypted).
5. Persists a :class:`app.db.models.PromptCallLog` row for the call (or
   a ``skipped`` row when the rules short-circuited).

The output is a :class:`ClassifyOutcome` so workers can record per-run
counts without re-reading the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import ConnectedAccount, Email, PromptCallLog
from app.domain.providers import EmailAddress, EmailMessage, UnsubscribeInfo
from app.llm.client import (
    LLMClient,
    LLMClientError,
    PromptCallRecord,
    render_prompt,
)
from app.llm.schemas import TriageDecision
from app.services.classification.repository import (
    ClassificationsRepo,
    ClassificationWrite,
)
from app.services.classification.rubric import RuleDecision, RuleEngine, load_default_rules
from app.services.ingestion.content import decrypt_excerpt

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher
    from app.services.prompts.registry import RegisteredPrompt


logger = get_logger(__name__)


_LOW_CONFIDENCE_THRESHOLD = 0.55
"""Below this rule confidence we still call the LLM (plan §6)."""

_NEEDS_REVIEW_THRESHOLD = 0.55
"""Below this model confidence we force ``needs_review`` (plan §6)."""


@dataclass(frozen=True)
class ClassifyInputs:
    """Everything the pipeline needs to classify one email.

    Attributes:
        email_id: Target email's id.
        user_id: Owning user (bound into encryption context).
        prompt: The registered triage prompt loaded from the registry.
        llm: Configured :class:`LLMClient`.
        repo: Encrypt-on-write :class:`ClassificationsRepo`.
        prompt_version_id: ``prompt_versions.id`` matching ``prompt``.
        content_cipher: Optional content-at-rest cipher for body excerpts.
    """

    email_id: UUID
    user_id: UUID
    prompt: RegisteredPrompt
    llm: LLMClient
    repo: ClassificationsRepo
    prompt_version_id: UUID
    content_cipher: EnvelopeCipher | None = None


@dataclass(frozen=True)
class ClassifyOutcome:
    """Result returned to the worker handler.

    Attributes:
        email_id: Echoed back for convenience.
        label: Final label persisted.
        score: Confidence in ``[0, 1]`` (as float for logging).
        decision_source: ``rule`` / ``model`` / ``hybrid``.
        tokens_in: Tokens billed (0 when rules short-circuited).
        tokens_out: Tokens billed.
        cost_usd: Summed cost of the LLM call; ``0`` otherwise.
        llm_used: True when at least one LLM call happened.
    """

    email_id: UUID
    label: str
    score: float
    decision_source: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    llm_used: bool


async def classify_one(
    inputs: ClassifyInputs,
    *,
    session: AsyncSession,
    rule_engine: RuleEngine | None = None,
    run_id: UUID | None = None,
) -> ClassifyOutcome:
    """Classify one email end-to-end.

    Args:
        inputs: Collaborator bundle.
        session: Active async session (caller owns commit).
        rule_engine: Optional pre-loaded engine; loaded from the DB
            when ``None`` so the first call per run doesn't pay the
            snapshot cost.
        run_id: Optional digest-run scope for the prompt-call-log row.

    Returns:
        :class:`ClassifyOutcome`.

    Raises:
        LookupError: When the email row has vanished between enqueue
            and dispatch.
    """
    email_row = await session.get(Email, inputs.email_id)
    if email_row is None:
        raise LookupError(f"email {inputs.email_id} not found")

    account_row = await session.get(ConnectedAccount, email_row.account_id)
    if account_row is None:
        raise LookupError(f"account {email_row.account_id} not found")

    engine = rule_engine
    if engine is None:
        engine = await load_default_rules(session, user_id=inputs.user_id)

    email_bm = _row_to_boundary(email_row)
    rule_decision = engine.evaluate(email_bm)

    if rule_decision is not None and rule_decision.confidence >= _LOW_CONFIDENCE_THRESHOLD:
        await _log_skipped(
            session,
            prompt_version_id=inputs.prompt_version_id,
            email_id=inputs.email_id,
            run_id=run_id,
        )
        return await _persist_rule_only(
            session=session,
            inputs=inputs,
            rule_decision=rule_decision,
        )

    # LLM consultation path — either the rules missed, or the rules
    # matched with confidence < threshold (hybrid decision).
    rendered = render_prompt(
        inputs.prompt.spec,
        variables={
            "rubric_summary": _rubric_summary(rule_decision),
            "from_addr": email_bm.from_addr.email,
            "subject": email_bm.subject,
            "plain_text_excerpt": _excerpt_for(
                email_bm,
                email_row,
                user_id=inputs.user_id,
                cipher=inputs.content_cipher,
            ),
        },
    )

    async def _log_call(record: PromptCallRecord) -> None:
        await _persist_call_log(session=session, record=record, run_id=run_id)

    try:
        response = await inputs.llm.call(
            spec=inputs.prompt.spec,
            rendered_prompt=rendered,
            schema=TriageDecision,
            prompt_version_id=inputs.prompt_version_id,
            email_id=inputs.email_id,
            run_id=run_id,
            log_call=_log_call,
        )
    except LLMClientError as exc:
        logger.warning(
            "classify.llm_failed_all_providers",
            email_id=str(inputs.email_id),
            error=str(exc),
        )
        # Graceful degradation: persist a needs_review row.
        return await _persist_needs_review(
            session=session,
            inputs=inputs,
            reason=str(exc),
        )

    triage = response.parsed
    assert isinstance(triage, TriageDecision)

    final_label = triage.category
    final_conf = triage.confidence
    if triage.confidence < _NEEDS_REVIEW_THRESHOLD:
        final_label = "needs_review"
    final_is_newsletter = triage.is_newsletter if final_label != "needs_review" else False
    final_is_job_candidate = triage.is_job_candidate if final_label != "needs_review" else False

    decision_source = "model" if rule_decision is None else "hybrid"
    reasons_payload: dict[str, object] = {
        "source": decision_source,
        "model_reasons": triage.reasons_short,
        "model_confidence": triage.confidence,
        "model_category": triage.category,
        "is_newsletter": triage.is_newsletter,
        "is_job_candidate": triage.is_job_candidate,
    }
    if rule_decision is not None:
        reasons_payload["rule_reasons"] = list(rule_decision.reasons)
        reasons_payload["rule_label"] = rule_decision.label
        reasons_payload["rule_confidence"] = rule_decision.confidence
        reasons_payload["rule_version"] = rule_decision.rubric_version

    await inputs.repo.upsert(
        session,
        ClassificationWrite(
            email_id=inputs.email_id,
            label=final_label,
            score=_to_decimal(final_conf),
            rubric_version=rule_decision.rubric_version if rule_decision else 0,
            prompt_version_id=inputs.prompt_version_id,
            decision_source=decision_source,
            model=response.call_result.model,
            tokens_in=response.call_result.tokens_in,
            tokens_out=response.call_result.tokens_out,
            is_newsletter=final_is_newsletter,
            is_job_candidate=final_is_job_candidate,
            reasons=reasons_payload,
            user_id=inputs.user_id,
        ),
    )

    return ClassifyOutcome(
        email_id=inputs.email_id,
        label=final_label,
        score=final_conf,
        decision_source=decision_source,
        tokens_in=response.call_result.tokens_in,
        tokens_out=response.call_result.tokens_out,
        cost_usd=response.call_result.cost_usd,
        llm_used=True,
    )


async def _persist_rule_only(
    *,
    session: AsyncSession,
    inputs: ClassifyInputs,
    rule_decision: RuleDecision,
) -> ClassifyOutcome:
    """Write the ``classifications`` row for a rule-only verdict."""
    reasons_payload: dict[str, object] = {
        "source": "rule",
        "rule_reasons": list(rule_decision.reasons),
        "rule_label": rule_decision.label,
        "rule_confidence": rule_decision.confidence,
        "rule_version": rule_decision.rubric_version,
        "is_newsletter": rule_decision.is_newsletter,
        "is_job_candidate": rule_decision.is_job_candidate,
    }
    await inputs.repo.upsert(
        session,
        ClassificationWrite(
            email_id=inputs.email_id,
            label=rule_decision.label,
            score=_to_decimal(rule_decision.confidence),
            rubric_version=rule_decision.rubric_version,
            prompt_version_id=None,
            decision_source="rule",
            model="",
            tokens_in=0,
            tokens_out=0,
            is_newsletter=rule_decision.is_newsletter,
            is_job_candidate=rule_decision.is_job_candidate,
            reasons=reasons_payload,
            user_id=inputs.user_id,
        ),
    )
    return ClassifyOutcome(
        email_id=inputs.email_id,
        label=rule_decision.label,
        score=rule_decision.confidence,
        decision_source="rule",
        tokens_in=0,
        tokens_out=0,
        cost_usd=Decimal("0"),
        llm_used=False,
    )


async def _persist_needs_review(
    *,
    session: AsyncSession,
    inputs: ClassifyInputs,
    reason: str,
) -> ClassifyOutcome:
    """Persist a ``needs_review`` verdict when all providers fail."""
    reasons_payload: dict[str, object] = {
        "source": "error",
        "error": reason,
    }
    await inputs.repo.upsert(
        session,
        ClassificationWrite(
            email_id=inputs.email_id,
            label="needs_review",
            score=Decimal("0.0"),
            rubric_version=0,
            prompt_version_id=None,
            decision_source="model",
            model="",
            tokens_in=0,
            tokens_out=0,
            is_newsletter=False,
            is_job_candidate=False,
            reasons=reasons_payload,
            user_id=inputs.user_id,
        ),
    )
    return ClassifyOutcome(
        email_id=inputs.email_id,
        label="needs_review",
        score=0.0,
        decision_source="model",
        tokens_in=0,
        tokens_out=0,
        cost_usd=Decimal("0"),
        llm_used=False,
    )


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


async def _log_skipped(
    session: AsyncSession,
    *,
    prompt_version_id: UUID,
    email_id: UUID,
    run_id: UUID | None,
) -> None:
    """Record a ``skipped`` prompt-call row when rules short-circuited.

    We still want a row so cost-attribution queries observe the
    pipeline shape (rule-only vs LLM).
    """
    session.add(
        PromptCallLog(
            prompt_version_id=prompt_version_id,
            email_id=email_id,
            model="",
            tokens_in=0,
            tokens_out=0,
            tokens_cache_read=0,
            tokens_cache_write=0,
            cost_usd=Decimal("0"),
            latency_ms=0,
            status="skipped",
            provider="rule",
            run_id=run_id,
        ),
    )
    await session.flush()


def _row_to_boundary(row: Email) -> EmailMessage:
    """Convert an ORM row to an :class:`EmailMessage` boundary object."""
    list_unsub: UnsubscribeInfo | None = None
    if row.list_unsubscribe:
        list_unsub = UnsubscribeInfo.model_validate(row.list_unsubscribe)

    return EmailMessage(
        account_id=row.account_id,
        message_id=row.gmail_message_id,
        thread_id=row.thread_id,
        internal_date=row.internal_date,
        from_addr=EmailAddress(email=row.from_addr),
        to_addrs=tuple(EmailAddress(email=addr) for addr in row.to_addrs),
        cc_addrs=tuple(EmailAddress(email=addr) for addr in row.cc_addrs),
        subject=row.subject,
        snippet=row.snippet,
        labels=tuple(row.labels),
        list_unsubscribe=list_unsub,
        content_hash=bytes(row.content_hash),
        size_bytes=row.size_bytes,
    )


def _rubric_summary(decision: RuleDecision | None) -> str:
    """Produce a one-line rubric hint for the prompt."""
    if decision is None:
        return "no rubric match"
    return (
        f"rubric matched {decision.label} (confidence {decision.confidence:.2f}); "
        "treat as advisory."
    )


def _excerpt_for(
    email: EmailMessage,
    row: Email,
    *,
    user_id: UUID,
    cipher: EnvelopeCipher | None,
) -> str:
    """Return the best excerpt for the prompt: blob excerpt or snippet."""
    excerpt = decrypt_excerpt(row.body, user_id=user_id, cipher=cipher)
    if excerpt:
        return excerpt
    return email.snippet or ""


def _to_decimal(value: float) -> Decimal:
    """Convert a confidence float to a quantized Decimal (3 dp)."""
    return Decimal(str(value)).quantize(Decimal("0.001"))


# Touched at import to avoid ``utcnow`` being flagged unused by the
# linter when no callsite picks it up (workers reach through kwargs).
_ = utcnow

__all__ = ["ClassifyInputs", "ClassifyOutcome", "classify_one"]
