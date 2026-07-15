"""Digest-run lifecycle helpers shared by worker stages.

Manual and scheduled scans write a ``digest_runs`` row before fan-out.
The pipeline itself is distributed across SQS queues, so each worker
stage opportunistically recomputes whether any DB-visible work remains
for the run and finalizes the row once processing has drained.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.sql import Executable

from app.core.app_config import get_app_config
from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import (
    Classification,
    ConnectedAccount,
    DigestRun,
    DigestRunEmail,
    Email,
    PromptCallLog,
    PromptVersion,
    Summary,
    TechNewsCluster,
    User,
)
from app.llm.schemas import CategoryDigestCategory
from app.services.email_labels import unread_email_filter
from app.workers.messages import CategoryDigestMessage

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


_APP_CONFIG = get_app_config()
_SUMMARIZABLE_LABELS: tuple[str, ...] = _APP_CONFIG.taxonomy.summarizable_labels
_FAILED_RUN_ERROR = "One or more LLM provider calls failed during the scan."
_NON_FATAL_PROMPT_NAMES: tuple[str, ...] = ("unsubscribe_borderline", "category_digest")
_UNSUBSCRIBE_HYGIENE_ENQUEUED_KEY = "unsubscribe_hygiene_enqueued"
logger = get_logger(__name__)

CategoryDigestSender = Callable[[CategoryDigestMessage], None]
"""Synchronous sender for category digest queue messages."""

CategoryDigestBuilder = Callable[[CategoryDigestMessage], Awaitable[None]]
"""Async inline builder for local/test category digest execution."""


class RunProgressSnapshot(BaseModel):
    """Current database-visible progress for one digest run.

    Attributes:
        ingested: Emails attached to the run membership set.
        classified: Member emails with classifications.
        summarized: Member emails and run clusters with summaries.
        new_must_read: Member emails classified as must-read.
        pending_unclassified: Member emails that still need classification.
        pending_summaries: Member emails that still need summaries.
        pending_clusters: Whether the run still needs a tech-news cluster summary.
        pending_category_summaries: Category digest rows still missing for
            non-empty summarizable categories.
        prompt_errors: Fatal failed provider-call rows written for this run.
        cost_cents: Rounded prompt cost in cents for this run.
    """

    model_config = ConfigDict(frozen=True)

    ingested: int = Field(..., ge=0, description="Emails attached to the run.")
    classified: int = Field(..., ge=0, description="Member emails with classifications.")
    summarized: int = Field(..., ge=0, description="Member summaries and clusters.")
    new_must_read: int = Field(..., ge=0, description="Member must-read classifications.")
    pending_unclassified: int = Field(..., ge=0, description="Emails lacking classification.")
    pending_summaries: int = Field(..., ge=0, description="Summarizable emails lacking summary.")
    pending_clusters: int = Field(..., ge=0, description="Missing tech-news cluster summaries.")
    pending_category_summaries: int = Field(
        ...,
        ge=0,
        description="Missing run/category digest summaries.",
    )
    prompt_errors: int = Field(..., ge=0, description="Failed prompt-call rows for the run.")
    cost_cents: int = Field(..., ge=0, description="Rounded run cost in cents.")

    @property
    def pending_total(self) -> int:
        """Return the total count of incomplete DB-visible work items."""
        return (
            self.pending_unclassified
            + self.pending_summaries
            + self.pending_clusters
            + self.pending_category_summaries
        )


async def stamp_run_membership(
    *,
    session: AsyncSession,
    run_id: UUID | None,
    email_ids: Iterable[UUID],
) -> int:
    """Attach emails to a digest run's explicit processing boundary.

    Args:
        session: Active database session.
        run_id: Digest-run id to stamp. ``None`` is a no-op for legacy
            ad-hoc worker paths.
        email_ids: Email ids included in the run.

    Returns:
        Count of newly inserted membership edges.
    """
    if run_id is None:
        return 0

    unique_ids = tuple(dict.fromkeys(email_ids))
    if not unique_ids:
        return 0

    existing = set(
        (
            await session.execute(
                select(DigestRunEmail.email_id).where(
                    DigestRunEmail.run_id == run_id,
                    DigestRunEmail.email_id.in_(unique_ids),
                ),
            )
        )
        .scalars()
        .all(),
    )
    new_rows = [
        DigestRunEmail(run_id=run_id, email_id=email_id)
        for email_id in unique_ids
        if email_id not in existing
    ]
    session.add_all(new_rows)
    await session.flush()
    return len(new_rows)


async def mark_run_running(session: AsyncSession, run_id: UUID | None) -> None:
    """Move a queued run to ``running``.

    Args:
        session: Active database session.
        run_id: Digest-run id carried by the worker message.
    """
    if run_id is None:
        return
    run = await session.get(DigestRun, run_id)
    if run is None or run.status != "queued":
        return
    run.status = "running"
    await session.flush()


async def mark_unsubscribe_hygiene_enqueued(
    *,
    session: AsyncSession,
    run_id: UUID | None,
    account_id: UUID,
) -> bool:
    """Record that unsubscribe hygiene was enqueued for an account/run.

    Args:
        session: Active database session.
        run_id: Digest-run id carried by the worker message. ``None``
            preserves legacy ad-hoc behavior and returns ``True``.
        account_id: Connected account whose hygiene aggregate is being
            enqueued.

    Returns:
        ``True`` when the caller should enqueue a hygiene message,
        ``False`` when this account/run was already marked.
    """
    if run_id is None:
        return True
    run = (
        await session.execute(
            select(DigestRun).where(DigestRun.id == run_id).with_for_update(),
        )
    ).scalar_one_or_none()
    if run is None:
        return False

    stats = dict(run.stats) if isinstance(run.stats, dict) else {}
    raw_ids = stats.get(_UNSUBSCRIBE_HYGIENE_ENQUEUED_KEY)
    enqueued = (
        {item for item in raw_ids if isinstance(item, str)} if isinstance(raw_ids, list) else set()
    )
    account_key = str(account_id)
    if account_key in enqueued:
        return False

    enqueued.add(account_key)
    stats[_UNSUBSCRIBE_HYGIENE_ENQUEUED_KEY] = sorted(enqueued)
    run.stats = stats
    await session.flush()
    return True


async def maybe_finalize_run(
    *,
    session: AsyncSession,
    user_id: UUID,
    run_id: UUID | None,
    category_digest_sender: CategoryDigestSender | None = None,
    category_digest_builder: CategoryDigestBuilder | None = None,
) -> bool:
    """Finalize a digest run when no DB-visible work remains.

    The helper is intentionally idempotent: every stage can call it
    after committing its own row-level work. It waits for all recoverable
    work to drain, then marks the run failed when provider errors were
    recorded or complete otherwise. Failed work items are excluded from
    the pending counters so an exhausted provider chain cannot strand a
    run indefinitely.

    Args:
        session: Active database session.
        user_id: Owner of the run.
        run_id: Digest-run id carried by the worker message.
        category_digest_sender: Optional queue sender for missing
            category digest messages.
        category_digest_builder: Optional inline builder used in local
            and test paths where no summarize queue is configured.

    Returns:
        ``True`` when the run reached a terminal state during this call.
    """
    if run_id is None:
        return False
    run = await session.get(DigestRun, run_id)
    if run is None or run.user_id != user_id or run.status in {"complete", "failed"}:
        return False

    account_ids = await _account_scope(session=session, user_id=user_id, run=run)
    snapshot = await _progress_snapshot(
        session=session,
        user_id=user_id,
        run=run,
        account_ids=account_ids,
    )
    run.stats = _stats_payload(run=run, account_ids=account_ids, snapshot=snapshot)
    run.cost_cents = snapshot.cost_cents
    if run.status == "queued":
        run.status = "running"

    if snapshot.pending_unclassified == 0 and snapshot.pending_summaries == 0:
        built_inline = await _dispatch_missing_category_summaries(
            session=session,
            run=run,
            account_ids=account_ids,
            category_digest_sender=category_digest_sender,
            category_digest_builder=category_digest_builder,
        )
        if built_inline:
            snapshot = await _progress_snapshot(
                session=session,
                user_id=user_id,
                run=run,
                account_ids=account_ids,
            )

    run.stats = _stats_payload(run=run, account_ids=account_ids, snapshot=snapshot)
    run.cost_cents = snapshot.cost_cents
    if snapshot.pending_total == 0:
        failed = snapshot.prompt_errors > 0
        _finish_run(
            run=run,
            status="failed" if failed else "complete",
            error=_FAILED_RUN_ERROR if failed else None,
        )
        _log_run_terminal(run=run, snapshot=snapshot)
        await _clear_user_lock(
            session=session,
            user_id=user_id,
            run_id=run_id,
            completed=not failed,
        )
        await session.flush()
        return True

    await session.flush()
    return False


async def _account_scope(
    *,
    session: AsyncSession,
    user_id: UUID,
    run: DigestRun,
) -> tuple[UUID, ...]:
    """Return the connected-account ids that belong to ``run``."""
    stat_ids = _account_ids_from_stats(run.stats)
    if stat_ids:
        return stat_ids
    rows = (
        (
            await session.execute(
                select(ConnectedAccount.id).where(
                    ConnectedAccount.user_id == user_id,
                    ConnectedAccount.status == "active",
                    ConnectedAccount.auto_scan_enabled.is_(True),
                ),
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


def _account_ids_from_stats(stats: object) -> tuple[UUID, ...]:
    """Parse the optional ``account_ids`` list from a run stats payload."""
    if not isinstance(stats, dict):
        return ()
    raw_ids = stats.get("account_ids")
    if not isinstance(raw_ids, list):
        return ()
    parsed: list[UUID] = []
    for raw_id in raw_ids:
        if not isinstance(raw_id, str):
            continue
        try:
            parsed.append(UUID(raw_id))
        except ValueError:
            continue
    return tuple(parsed)


async def _progress_snapshot(
    *,
    session: AsyncSession,
    user_id: UUID,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> RunProgressSnapshot:
    """Compute current run progress from pipeline tables."""
    if not account_ids:
        return RunProgressSnapshot(
            ingested=0,
            classified=0,
            summarized=0,
            new_must_read=0,
            pending_unclassified=0,
            pending_summaries=0,
            pending_clusters=0,
            pending_category_summaries=0,
            prompt_errors=await _prompt_errors(session=session, run_id=run.id),
            cost_cents=await _cost_cents(session=session, run_id=run.id),
        )

    return RunProgressSnapshot(
        ingested=await _ingested_since(session=session, run=run, account_ids=account_ids),
        classified=await _classified_since(session=session, run=run, account_ids=account_ids),
        summarized=await _summarized_since(
            session=session,
            user_id=user_id,
            run=run,
            account_ids=account_ids,
        ),
        new_must_read=await _must_read_since(session=session, run=run, account_ids=account_ids),
        pending_unclassified=await _pending_unclassified(
            session=session,
            run=run,
            account_ids=account_ids,
        ),
        pending_summaries=await _pending_summaries(
            session=session,
            run=run,
            account_ids=account_ids,
        ),
        pending_clusters=await _pending_clusters(
            session=session,
            user_id=user_id,
            run_id=run.id,
            account_ids=account_ids,
        ),
        pending_category_summaries=await _pending_category_summaries(
            session=session,
            run_id=run.id,
            account_ids=account_ids,
        ),
        prompt_errors=await _prompt_errors(session=session, run_id=run.id),
        cost_cents=await _cost_cents(session=session, run_id=run.id),
    )


async def _ingested_since(
    *,
    session: AsyncSession,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count member emails for the run."""
    return await _count(
        session,
        select(func.count(DigestRunEmail.email_id))
        .join(Email, Email.id == DigestRunEmail.email_id)
        .where(
            DigestRunEmail.run_id == run.id,
            Email.account_id.in_(account_ids),
        ),
    )


async def _classified_since(
    *,
    session: AsyncSession,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count classifications for member emails."""
    return await _count(
        session,
        select(func.count(Classification.id))
        .join(DigestRunEmail, DigestRunEmail.email_id == Classification.email_id)
        .join(Email, Email.id == Classification.email_id)
        .where(
            DigestRunEmail.run_id == run.id,
            Email.account_id.in_(account_ids),
        ),
    )


async def _summarized_since(
    *,
    session: AsyncSession,
    user_id: UUID,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count per-email and cluster summaries for this run boundary."""
    per_email = await _count(
        session,
        select(func.count(Summary.id))
        .join(DigestRunEmail, DigestRunEmail.email_id == Summary.email_id)
        .join(Email, Email.id == Summary.email_id)
        .where(
            DigestRunEmail.run_id == run.id,
            Summary.kind == "email",
            Email.account_id.in_(account_ids),
        ),
    )
    clusters = await _count(
        session,
        select(func.count(Summary.id))
        .join(TechNewsCluster, TechNewsCluster.id == Summary.cluster_id)
        .where(
            Summary.kind == "tech_news_cluster",
            TechNewsCluster.user_id == user_id,
            TechNewsCluster.run_id == run.id,
        ),
    )
    return per_email + clusters


async def _must_read_since(
    *,
    session: AsyncSession,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count member-email must-read classifications."""
    return await _count(
        session,
        select(func.count(Classification.id))
        .join(DigestRunEmail, DigestRunEmail.email_id == Classification.email_id)
        .join(Email, Email.id == Classification.email_id)
        .where(
            DigestRunEmail.run_id == run.id,
            Email.account_id.in_(account_ids),
            Classification.label == "must_read",
        ),
    )


async def _pending_unclassified(
    *,
    session: AsyncSession,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count member emails that do not have a classification."""
    return await _count(
        session,
        select(func.count(DigestRunEmail.email_id))
        .join(Email, Email.id == DigestRunEmail.email_id)
        .outerjoin(Classification, Classification.email_id == Email.id)
        .where(
            DigestRunEmail.run_id == run.id,
            Email.account_id.in_(account_ids),
            unread_email_filter(session),
            Classification.email_id.is_(None),
        ),
    )


async def _pending_summaries(
    *,
    session: AsyncSession,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count member emails still awaiting a summary or terminal failure."""
    fatal_error = (
        select(PromptCallLog.id)
        .outerjoin(PromptVersion, PromptVersion.id == PromptCallLog.prompt_version_id)
        .where(
            PromptCallLog.run_id == run.id,
            PromptCallLog.email_id == Email.id,
            PromptCallLog.status == "error",
            or_(
                PromptVersion.name.is_(None),
                PromptVersion.name.not_in(_NON_FATAL_PROMPT_NAMES),
            ),
        )
        .exists()
    )
    return await _count(
        session,
        select(func.count(DigestRunEmail.email_id))
        .join(Email, Email.id == DigestRunEmail.email_id)
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(Summary, Summary.email_id == Email.id)
        .where(
            DigestRunEmail.run_id == run.id,
            Email.account_id.in_(account_ids),
            unread_email_filter(session),
            or_(
                Classification.label.in_(_SUMMARIZABLE_LABELS),
                Classification.is_newsletter.is_(True),
            ),
            Summary.email_id.is_(None),
            ~fatal_error,
        ),
    )


async def _pending_clusters(
    *,
    session: AsyncSession,
    user_id: UUID,
    run_id: UUID,
    account_ids: tuple[UUID, ...],
) -> int:
    """Return ``1`` when a run-scope tech-news cluster is still missing."""
    newsletter_count = await _count(
        session,
        select(func.count(Email.id))
        .join(DigestRunEmail, DigestRunEmail.email_id == Email.id)
        .join(Classification, Classification.email_id == Email.id)
        .where(
            DigestRunEmail.run_id == run_id,
            Email.account_id.in_(account_ids),
            unread_email_filter(session),
            or_(
                Classification.label == "newsletter",
                Classification.is_newsletter.is_(True),
            ),
        ),
    )
    if newsletter_count < 2:
        return 0
    failed_cluster = await _count(
        session,
        select(func.count(PromptCallLog.id))
        .outerjoin(PromptVersion, PromptVersion.id == PromptCallLog.prompt_version_id)
        .where(
            PromptCallLog.run_id == run_id,
            PromptCallLog.email_id.is_(None),
            PromptCallLog.status == "error",
            or_(
                PromptVersion.name.is_(None),
                PromptVersion.name == "newsletter_group",
            ),
        ),
    )
    if failed_cluster > 0:
        return 0
    summary_id = (
        await session.execute(
            select(Summary.id)
            .join(TechNewsCluster, TechNewsCluster.id == Summary.cluster_id)
            .where(
                TechNewsCluster.user_id == user_id,
                TechNewsCluster.run_id == run_id,
                Summary.kind == "tech_news_cluster",
            )
            .limit(1),
        )
    ).scalar_one_or_none()
    return 0 if summary_id is not None else 1


async def _pending_category_summaries(
    *,
    session: AsyncSession,
    run_id: UUID,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count missing run/category digest summaries."""
    missing = await _missing_category_digest_categories(
        session=session,
        run_id=run_id,
        account_ids=account_ids,
    )
    return len(missing)


async def _missing_category_digest_categories(
    *,
    session: AsyncSession,
    run_id: UUID,
    account_ids: tuple[UUID, ...],
) -> tuple[CategoryDigestCategory, ...]:
    """Return non-empty summarizable categories lacking digest rows."""
    if not account_ids:
        return ()
    rows = (
        await session.execute(
            select(Classification.label, func.count(Classification.id))
            .join(DigestRunEmail, DigestRunEmail.email_id == Classification.email_id)
            .join(Email, Email.id == Classification.email_id)
            .join(Summary, Summary.email_id == Classification.email_id)
            .where(
                DigestRunEmail.run_id == run_id,
                Email.account_id.in_(account_ids),
                unread_email_filter(session),
                Classification.label.in_(_SUMMARIZABLE_LABELS),
                Summary.kind == "email",
            )
            .group_by(Classification.label),
        )
    ).all()
    non_empty = {str(label) for label, count in rows if int(count) > 0}
    if not non_empty:
        return ()
    existing = set(
        (
            await session.execute(
                select(Summary.category).where(
                    Summary.kind == "category_digest",
                    Summary.run_id == run_id,
                    Summary.category.in_(tuple(non_empty)),
                ),
            )
        )
        .scalars()
        .all(),
    )
    missing = [
        cast(CategoryDigestCategory, category)
        for category in _SUMMARIZABLE_LABELS
        if category in non_empty and category not in existing
    ]
    return tuple(missing)


async def _dispatch_missing_category_summaries(
    *,
    session: AsyncSession,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
    category_digest_sender: CategoryDigestSender | None,
    category_digest_builder: CategoryDigestBuilder | None,
) -> bool:
    """Send or build missing category digests once per run/category."""
    missing = await _missing_category_digest_categories(
        session=session,
        run_id=run.id,
        account_ids=account_ids,
    )
    if not missing:
        return False

    already_enqueued = _category_digests_enqueued(run.stats)
    dispatched: list[str] = []
    built_inline = False
    for category in missing:
        if category in already_enqueued:
            continue
        message = CategoryDigestMessage(run_id=run.id, category=category)
        if category_digest_sender is not None:
            category_digest_sender(message)
        elif category_digest_builder is not None:
            await category_digest_builder(message)
            built_inline = True
        else:
            logger.warning(
                "digest.category.no_dispatcher",
                run_id=str(run.id),
                category=category,
            )
            continue
        dispatched.append(category)

    if dispatched:
        _mark_category_digests_enqueued(run=run, categories=tuple(dispatched))
    return built_inline


def _category_digests_enqueued(stats: object) -> frozenset[str]:
    """Return categories already dispatched for digesting from run stats."""
    if not isinstance(stats, dict):
        return frozenset()
    raw = stats.get("category_digests_enqueued")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(item) for item in raw if isinstance(item, str))


def _mark_category_digests_enqueued(
    *,
    run: DigestRun,
    categories: tuple[str, ...],
) -> None:
    """Persist category digest dispatch markers in the run stats JSON."""
    existing = dict(run.stats) if isinstance(run.stats, dict) else {}
    merged = sorted(_category_digests_enqueued(existing).union(categories))
    existing["category_digests_enqueued"] = merged
    run.stats = existing


async def _prompt_errors(*, session: AsyncSession, run_id: UUID) -> int:
    """Count fatal failed prompt-call rows for ``run_id``."""
    return await _count(
        session,
        select(func.count(PromptCallLog.id))
        .outerjoin(PromptVersion, PromptVersion.id == PromptCallLog.prompt_version_id)
        .where(
            PromptCallLog.run_id == run_id,
            PromptCallLog.status == "error",
            or_(
                PromptVersion.name.is_(None),
                PromptVersion.name.not_in(_NON_FATAL_PROMPT_NAMES),
            ),
        ),
    )


async def _cost_cents(*, session: AsyncSession, run_id: UUID) -> int:
    """Return rounded provider cost in cents for ``run_id``."""
    value = (
        await session.execute(
            select(func.coalesce(func.sum(PromptCallLog.cost_usd), Decimal("0"))).where(
                PromptCallLog.run_id == run_id,
            ),
        )
    ).scalar_one()
    cost = value if isinstance(value, Decimal) else Decimal(str(value))
    return int((cost * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def _count(session: AsyncSession, statement: Executable) -> int:
    """Execute a scalar count statement and return an ``int``."""
    return int((await session.execute(statement)).scalar_one() or 0)


def _stats_payload(
    *,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
    snapshot: RunProgressSnapshot,
) -> dict[str, object]:
    """Merge public counters with private account-scope metadata."""
    existing = dict(run.stats) if isinstance(run.stats, dict) else {}
    existing.update(
        {
            "ingested": snapshot.ingested,
            "classified": snapshot.classified,
            "summarized": snapshot.summarized,
            "new_must_read": snapshot.new_must_read,
            "account_ids": [str(account_id) for account_id in account_ids],
        },
    )
    return existing


def _finish_run(*, run: DigestRun, status: str, error: str | None) -> None:
    """Stamp terminal fields on a digest run."""
    run.status = status
    run.completed_at = utcnow()
    run.error = error


def _log_run_terminal(*, run: DigestRun, snapshot: RunProgressSnapshot) -> None:
    """Emit the structured terminal-run event used by alarms."""
    logger.info(
        "digest.run",
        run_id=str(run.id),
        user_id=str(run.user_id),
        status=run.status,
        trigger_type=run.trigger_type,
        pending_total=snapshot.pending_total,
        prompt_errors=snapshot.prompt_errors,
        cost_cents=snapshot.cost_cents,
    )


async def _clear_user_lock(
    *,
    session: AsyncSession,
    user_id: UUID,
    run_id: UUID,
    completed: bool,
) -> None:
    """Clear the per-user idempotency lock for a terminal run."""
    user = await session.get(User, user_id)
    if user is None or user.current_run_id != str(run_id):
        return
    user.current_run_id = None
    user.current_run_started_at = None
    if completed:
        user.last_run_finished_at = utcnow()


__all__ = [
    "RunProgressSnapshot",
    "mark_run_running",
    "mark_unsubscribe_hygiene_enqueued",
    "maybe_finalize_run",
    "stamp_run_membership",
]
