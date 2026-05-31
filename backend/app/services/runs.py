"""Digest-run lifecycle helpers shared by worker stages.

Manual and scheduled scans write a ``digest_runs`` row before fan-out.
The pipeline itself is distributed across SQS queues, so each worker
stage opportunistically recomputes whether any DB-visible work remains
for the run and finalizes the row once processing has drained.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.sql import Executable

from app.core.clock import utcnow
from app.db.models import (
    Classification,
    ConnectedAccount,
    DigestRun,
    Email,
    JobMatch,
    PromptCallLog,
    Summary,
    TechNewsCluster,
    User,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


_SUMMARIZABLE_LABELS: tuple[str, ...] = ("must_read", "good_to_read", "newsletter")
_JOB_LABEL = "job_candidate"
_FAILED_RUN_ERROR = "One or more LLM provider calls failed during the scan."


class RunProgressSnapshot(BaseModel):
    """Current database-visible progress for one digest run.

    Attributes:
        ingested: Emails created for the run's account scope since the run started.
        classified: Classifications created for the scope since the run started.
        summarized: Summaries created for the scope since the run started.
        new_must_read: Must-read classifications created since the run started.
        pending_unclassified: Account-scope emails that still need classification.
        pending_summaries: Account-scope classified emails that still need summaries.
        pending_jobs: Account-scope job-candidate emails that still need extraction.
        pending_clusters: Whether the run still needs a tech-news cluster summary.
        prompt_errors: Failed provider-call rows written for this run.
        cost_cents: Rounded prompt cost in cents for this run.
    """

    model_config = ConfigDict(frozen=True)

    ingested: int = Field(..., ge=0, description="Emails created since run start.")
    classified: int = Field(..., ge=0, description="Classifications created since run start.")
    summarized: int = Field(..., ge=0, description="Summaries created since run start.")
    new_must_read: int = Field(..., ge=0, description="Must-read classifications since start.")
    pending_unclassified: int = Field(..., ge=0, description="Emails lacking classification.")
    pending_summaries: int = Field(..., ge=0, description="Summarizable emails lacking summary.")
    pending_jobs: int = Field(..., ge=0, description="Job-candidate emails lacking job match.")
    pending_clusters: int = Field(..., ge=0, description="Missing tech-news cluster summaries.")
    prompt_errors: int = Field(..., ge=0, description="Failed prompt-call rows for the run.")
    cost_cents: int = Field(..., ge=0, description="Rounded run cost in cents.")

    @property
    def pending_total(self) -> int:
        """Return the total count of incomplete DB-visible work items."""
        return (
            self.pending_unclassified
            + self.pending_summaries
            + self.pending_jobs
            + self.pending_clusters
        )


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


async def maybe_finalize_run(
    *,
    session: AsyncSession,
    user_id: UUID,
    run_id: UUID | None,
) -> bool:
    """Finalize a digest run when no DB-visible work remains.

    The helper is intentionally idempotent: every stage can call it
    after committing its own row-level work. It marks the run failed
    when provider errors were recorded, complete when all pending work
    has drained, and otherwise leaves it running.

    Args:
        session: Active database session.
        user_id: Owner of the run.
        run_id: Digest-run id carried by the worker message.

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

    if snapshot.prompt_errors > 0:
        _finish_run(run=run, status="failed", error=_FAILED_RUN_ERROR)
        await _clear_user_lock(session=session, user_id=user_id, run_id=run_id, completed=False)
        await session.flush()
        return True
    if snapshot.pending_total == 0:
        _finish_run(run=run, status="complete", error=None)
        await _clear_user_lock(session=session, user_id=user_id, run_id=run_id, completed=True)
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
            pending_jobs=0,
            pending_clusters=0,
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
            account_ids=account_ids,
        ),
        pending_summaries=await _pending_summaries(session=session, account_ids=account_ids),
        pending_jobs=await _pending_jobs(session=session, account_ids=account_ids),
        pending_clusters=await _pending_clusters(
            session=session,
            user_id=user_id,
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
    """Count emails created since run start."""
    return await _count(
        session,
        select(func.count(Email.id)).where(
            Email.account_id.in_(account_ids),
            Email.created_at >= run.started_at,
        ),
    )


async def _classified_since(
    *,
    session: AsyncSession,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count classifications created since run start."""
    return await _count(
        session,
        select(func.count(Classification.id))
        .join(Email, Email.id == Classification.email_id)
        .where(
            Email.account_id.in_(account_ids),
            Classification.created_at >= run.started_at,
        ),
    )


async def _summarized_since(
    *,
    session: AsyncSession,
    user_id: UUID,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count per-email and cluster summaries created since run start."""
    per_email = await _count(
        session,
        select(func.count(Summary.id))
        .join(Email, Email.id == Summary.email_id)
        .where(
            Summary.kind == "email",
            Email.account_id.in_(account_ids),
            Summary.created_at >= run.started_at,
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
            Summary.created_at >= run.started_at,
        ),
    )
    return per_email + clusters


async def _must_read_since(
    *,
    session: AsyncSession,
    run: DigestRun,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count must-read classifications created since run start."""
    return await _count(
        session,
        select(func.count(Classification.id))
        .join(Email, Email.id == Classification.email_id)
        .where(
            Email.account_id.in_(account_ids),
            Classification.label == "must_read",
            Classification.created_at >= run.started_at,
        ),
    )


async def _pending_unclassified(
    *,
    session: AsyncSession,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count account-scope emails that do not have a classification."""
    return await _count(
        session,
        select(func.count(Email.id))
        .outerjoin(Classification, Classification.email_id == Email.id)
        .where(
            Email.account_id.in_(account_ids),
            Classification.email_id.is_(None),
        ),
    )


async def _pending_summaries(
    *,
    session: AsyncSession,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count account-scope summarizable emails that lack summaries."""
    return await _count(
        session,
        select(func.count(Email.id))
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(Summary, Summary.email_id == Email.id)
        .where(
            Email.account_id.in_(account_ids),
            or_(
                Classification.label.in_(_SUMMARIZABLE_LABELS),
                Classification.is_newsletter.is_(True),
            ),
            Summary.email_id.is_(None),
        ),
    )


async def _pending_jobs(
    *,
    session: AsyncSession,
    account_ids: tuple[UUID, ...],
) -> int:
    """Count account-scope job candidates that lack extraction rows."""
    return await _count(
        session,
        select(func.count(Email.id))
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(JobMatch, JobMatch.email_id == Email.id)
        .where(
            Email.account_id.in_(account_ids),
            or_(
                Classification.is_job_candidate.is_(True),
                Classification.label == _JOB_LABEL,
            ),
            JobMatch.email_id.is_(None),
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
        .join(Classification, Classification.email_id == Email.id)
        .where(
            Email.account_id.in_(account_ids),
            or_(
                Classification.label == "newsletter",
                Classification.is_newsletter.is_(True),
            ),
        ),
    )
    if newsletter_count < 2:
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


async def _prompt_errors(*, session: AsyncSession, run_id: UUID) -> int:
    """Count failed prompt-call rows for ``run_id``."""
    return await _count(
        session,
        select(func.count(PromptCallLog.id)).where(
            PromptCallLog.run_id == run_id,
            PromptCallLog.status == "error",
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


__all__ = ["RunProgressSnapshot", "mark_run_running", "maybe_finalize_run"]
