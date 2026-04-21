"""Phase 6 PWA/dashboard API router.

This router exposes cross-cutting read models for the React PWA without
moving pipeline ownership out of the worker/services layer. It is deliberately
thin: selectors live here, pipeline writes stay with their existing repos.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import current_user_id, db_session
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.db.models import (
    Classification,
    ConnectedAccount,
    DigestRun,
    Email,
    PromptCallLog,
    Summary,
    TechNewsCluster,
    TechNewsClusterMember,
    UserPreference,
)
from app.schemas.emails import EmailBucket, EmailRowOut
from app.schemas.frontend import (
    DigestCounts,
    DigestTodayResponse,
    ManualRunRequest,
    ManualRunResponse,
    NewsCluster,
    NewsDigestResponse,
    PreferencesPatchRequest,
    RunsListResponse,
    RunStats,
    RunStatusResponse,
    UserPreferencesOut,
)
from app.services.classification.repository import ClassificationsRepo
from app.services.summarization.repository import SummariesRepo
from app.workers.messages import IngestMessage

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import KmsClient
    from app.services.classification.dispatch import SqsSender


router = APIRouter(tags=["frontend"])

_BUCKETS: tuple[EmailBucket, ...] = ("must_read", "good_to_read", "ignore", "waste")
"""Primary user-facing triage buckets."""

_PREVIEW_LIMIT = 5
"""Dashboard preview size."""


@router.get(
    "/preferences",
    response_model=UserPreferencesOut,
    summary="Get user preferences",
)
async def get_preferences(
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> UserPreferencesOut:
    """Return the caller's preferences, inserting defaults on first use."""
    prefs = await _get_or_create_preferences(session=session, user_id=user_id)
    return _preferences_out(prefs)


@router.patch(
    "/preferences",
    response_model=UserPreferencesOut,
    summary="Update user preferences",
)
async def patch_preferences(
    payload: PreferencesPatchRequest,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> UserPreferencesOut:
    """Patch the caller's global preferences."""
    prefs = await _get_or_create_preferences(session=session, user_id=user_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is not None:
            setattr(prefs, key, value)
    await session.flush()
    return _preferences_out(prefs)


@router.post(
    "/runs",
    response_model=ManualRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a manual digest run",
)
async def start_manual_run(
    payload: ManualRunRequest,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> ManualRunResponse:
    """Create a digest run and enqueue one ingest message per selected account."""
    accounts = await _selected_accounts(
        session=session,
        user_id=user_id,
        account_ids=payload.account_ids,
    )
    now = utcnow()
    run = DigestRun(
        user_id=user_id,
        status="queued",
        trigger_type="manual",
        started_at=now,
        completed_at=None,
        stats={
            "ingested": 0,
            "classified": 0,
            "summarized": 0,
            "new_must_read": 0,
        },
        cost_cents=0,
    )
    session.add(run)
    await session.flush()
    _enqueue_ingest_messages(run_id=run.id, user_id=user_id, accounts=accounts)
    return ManualRunResponse(run_id=run.id, accounts_queued=len(accounts))


@router.get(
    "/runs/{run_id}",
    response_model=RunStatusResponse,
    summary="Get digest-run status",
)
async def get_run(
    run_id: UUID,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> RunStatusResponse:
    """Return one owned digest-run row for polling."""
    run = await _load_owned_run(session=session, user_id=user_id, run_id=run_id)
    return _run_out(run)


@router.get(
    "/history",
    response_model=RunsListResponse,
    summary="List digest-run history",
)
async def list_history(
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    limit: int = Query(default=25, ge=1, le=100),
) -> RunsListResponse:
    """Return newest-first digest-run rows for the history page."""
    rows = (
        (
            await session.execute(
                select(DigestRun)
                .where(DigestRun.user_id == user_id)
                .order_by(DigestRun.started_at.desc())
                .limit(limit),
            )
        )
        .scalars()
        .all()
    )
    return RunsListResponse(runs=tuple(_run_out(row) for row in rows))


@router.get(
    "/digest/today",
    response_model=DigestTodayResponse,
    summary="Get today's digest summary",
)
async def digest_today(
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> DigestTodayResponse:
    """Return dashboard counters, cost, and a must-read preview."""
    counts = await _digest_counts(session=session, user_id=user_id)
    last_run = (
        await session.execute(
            select(DigestRun)
            .where(
                DigestRun.user_id == user_id,
                DigestRun.status == "complete",
            )
            .order_by(DigestRun.completed_at.desc().nullslast(), DigestRun.started_at.desc())
            .limit(1),
        )
    ).scalar_one_or_none()
    cost_cents = await _cost_cents_today(session=session, user_id=user_id)
    preview = await _email_rows(
        session=session,
        user_id=user_id,
        settings=settings,
        bucket="must_read",
        account_id=None,
        limit=_PREVIEW_LIMIT,
    )
    generated_at = last_run.completed_at if last_run and last_run.completed_at else None
    return DigestTodayResponse(
        generated_at=generated_at,
        cost_cents_today=cost_cents,
        counts=counts,
        must_read_preview=preview,
        last_successful_run_at=generated_at,
    )


@router.get(
    "/news",
    response_model=NewsDigestResponse,
    summary="Get tech-news digest",
)
async def news_digest(
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
    limit: int = Query(default=20, ge=1, le=100),
) -> NewsDigestResponse:
    """Return summarized tech-news clusters for the caller."""
    rows = (
        await session.execute(
            select(TechNewsCluster, Summary)
            .join(Summary, Summary.cluster_id == TechNewsCluster.id)
            .where(
                TechNewsCluster.user_id == user_id,
                Summary.kind == "tech_news_cluster",
            )
            .order_by(TechNewsCluster.created_at.desc())
            .limit(limit),
        )
    ).all()
    repo = _summaries_repo(settings)
    clusters: list[NewsCluster] = []
    for cluster, summary in rows:
        member_ids = tuple(
            (
                await session.execute(
                    select(TechNewsClusterMember.email_id)
                    .where(TechNewsClusterMember.cluster_id == cluster.id)
                    .order_by(TechNewsClusterMember.sort_order.asc()),
                )
            )
            .scalars()
            .all()
        )
        label = cluster.topic_hint or cluster.cluster_key.replace("_", " ").title()
        clusters.append(
            NewsCluster(
                id=cluster.id,
                label=label,
                summary_md=repo.decrypt_cluster_body(row=summary, user_id=user_id),
                email_ids=member_ids,
            ),
        )
    return NewsDigestResponse(generated_at=utcnow(), clusters=tuple(clusters))


async def _get_or_create_preferences(
    *,
    session: AsyncSession,
    user_id: UUID,
) -> UserPreference:
    """Return the preference row, inserting default values if absent."""
    prefs = await session.get(UserPreference, user_id)
    if prefs is not None:
        return prefs
    prefs = UserPreference(user_id=user_id)
    session.add(prefs)
    await session.flush()
    return prefs


def _preferences_out(row: UserPreference) -> UserPreferencesOut:
    """Convert a preference ORM row into its API model."""
    retention = row.retention_policy_json if isinstance(row.retention_policy_json, dict) else {}
    return UserPreferencesOut(
        auto_execution_enabled=row.auto_execution_enabled,
        digest_send_hour_utc=row.digest_send_hour_utc,
        redact_pii=row.redact_pii,
        secure_offline_mode=row.secure_offline_mode,
        retention_policy_json=dict(retention),
    )


async def _selected_accounts(
    *,
    session: AsyncSession,
    user_id: UUID,
    account_ids: tuple[UUID, ...] | None,
) -> list[ConnectedAccount]:
    """Return owned active accounts selected for a manual run."""
    stmt = select(ConnectedAccount).where(
        ConnectedAccount.user_id == user_id,
        ConnectedAccount.status == "active",
        ConnectedAccount.auto_scan_enabled.is_(True),
    )
    if account_ids:
        stmt = stmt.where(ConnectedAccount.id.in_(account_ids))
    rows = (await session.execute(stmt)).scalars().all()
    if account_ids and len(rows) != len(set(account_ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account not found")
    return list(rows)


def _enqueue_ingest_messages(
    *,
    run_id: UUID,
    user_id: UUID,
    accounts: list[ConnectedAccount],
) -> None:
    """Best-effort enqueue to the ingest queue when API env is configured."""
    import os

    queue_url = os.environ.get("BRIEFED_INGEST_QUEUE_URL")
    if not queue_url:
        return
    import boto3  # type: ignore[import-untyped]

    sqs = cast("SqsSender", boto3.client("sqs"))
    for account in accounts:
        message = IngestMessage(
            user_id=user_id,
            account_id=account.id,
            run_id=run_id,
            store_raw_mime=False,
        )
        sqs.send_message(QueueUrl=queue_url, MessageBody=message.model_dump_json())


async def _load_owned_run(
    *,
    session: AsyncSession,
    user_id: UUID,
    run_id: UUID,
) -> DigestRun:
    """Load one digest-run row owned by the caller."""
    row = await session.get(DigestRun, run_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
    return row


def _run_out(row: DigestRun) -> RunStatusResponse:
    """Convert a ``digest_runs`` ORM row into its API model."""
    return RunStatusResponse(
        id=row.id,
        status=cast(Literal["queued", "running", "complete", "failed"], row.status),
        trigger_type=cast(Literal["scheduled", "manual"], row.trigger_type),
        started_at=row.started_at,
        completed_at=row.completed_at,
        stats=_run_stats(row.stats),
        cost_cents=row.cost_cents,
        error=row.error,
    )


def _run_stats(value: object) -> RunStats:
    """Sanitize the JSON run-stats payload into a typed model."""
    if not isinstance(value, dict):
        return RunStats()
    return RunStats(
        ingested=_int_value(value.get("ingested")),
        classified=_int_value(value.get("classified")),
        summarized=_int_value(value.get("summarized")),
        new_must_read=_int_value(value.get("new_must_read")),
    )


def _int_value(value: object) -> int:
    """Return a non-negative integer from an untyped JSON value."""
    try:
        return max(int(str(value)), 0)
    except ValueError:
        return 0


async def _digest_counts(
    *,
    session: AsyncSession,
    user_id: UUID,
) -> DigestCounts:
    """Return current counts by triage bucket for one user."""
    rows = (
        await session.execute(
            select(Classification.label, func.count(Classification.id))
            .join(Email, Email.id == Classification.email_id)
            .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
            .where(
                ConnectedAccount.user_id == user_id,
                Classification.label.in_(_BUCKETS),
            )
            .group_by(Classification.label),
        )
    ).all()
    counts = {bucket: 0 for bucket in _BUCKETS}
    for label, count in rows:
        if label in counts:
            counts[cast(EmailBucket, label)] = int(count)
    return DigestCounts(**counts)


async def _cost_cents_today(
    *,
    session: AsyncSession,
    user_id: UUID,
) -> int:
    """Return prompt spend since UTC midnight rounded to cents."""
    now = datetime.now(tz=UTC)
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    value = (
        await session.execute(
            select(func.coalesce(func.sum(PromptCallLog.cost_usd), 0))
            .join(Email, Email.id == PromptCallLog.email_id)
            .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
            .where(
                ConnectedAccount.user_id == user_id,
                PromptCallLog.created_at >= start,
            ),
        )
    ).scalar_one()
    cents = Decimal(str(value)) * Decimal("100")
    return max(int(cents.quantize(Decimal("1"))), 0)


async def _email_rows(
    *,
    session: AsyncSession,
    user_id: UUID,
    settings: Settings,
    bucket: EmailBucket | None,
    account_id: UUID | None,
    limit: int,
) -> tuple[EmailRowOut, ...]:
    """Return newest-first email rows for dashboard and triage pages."""
    stmt = (
        select(Email, ConnectedAccount, Classification, Summary)
        .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(Summary, Summary.email_id == Email.id)
        .where(ConnectedAccount.user_id == user_id)
        .order_by(Email.internal_date.desc())
        .limit(limit)
    )
    if bucket is not None:
        stmt = stmt.where(Classification.label == bucket)
    else:
        stmt = stmt.where(Classification.label.in_(_BUCKETS))
    if account_id is not None:
        stmt = stmt.where(Email.account_id == account_id)

    rows = (await session.execute(stmt)).all()
    classification_repo = _classification_repo(settings)
    summaries_repo = _summaries_repo(settings)
    items: list[EmailRowOut] = []
    for email, account, classification, summary in rows:
        items.append(
            EmailRowOut(
                id=email.id,
                account_email=account.email,
                thread_id=email.thread_id,
                subject=email.subject,
                sender=email.from_addr,
                received_at=email.internal_date,
                bucket=cast(EmailBucket, classification.label),
                confidence=float(classification.score),
                decision_source=_decision_source(classification.decision_source),
                reasons=_reason_strings(
                    classification_repo.decrypt_reasons(
                        row=classification,
                        user_id=user_id,
                    ),
                ),
                summary_excerpt=_summary_excerpt(
                    repo=summaries_repo,
                    summary=summary,
                    user_id=user_id,
                    fallback=email.snippet,
                ),
            ),
        )
    return tuple(items)


def _classification_repo(settings: Settings) -> ClassificationsRepo:
    """Return the classification repo wired with content crypto when needed."""
    if not settings.content_key_alias:
        return ClassificationsRepo(cipher=None)
    import boto3

    from app.core.security import EnvelopeCipher

    return ClassificationsRepo(
        cipher=EnvelopeCipher(
            key_id=settings.content_key_alias,
            client=cast("KmsClient", boto3.client("kms")),
        ),
    )


def _summaries_repo(settings: Settings) -> SummariesRepo:
    """Return the summary repo wired with content crypto when needed."""
    if not settings.content_key_alias:
        return SummariesRepo(cipher=None)
    import boto3

    from app.core.security import EnvelopeCipher

    return SummariesRepo(
        cipher=EnvelopeCipher(
            key_id=settings.content_key_alias,
            client=cast("KmsClient", boto3.client("kms")),
        ),
    )


def _decision_source(value: str) -> Literal["rule", "llm", "hybrid"]:
    """Map DB decision source to frontend vocabulary."""
    if value == "model":
        return "llm"
    if value == "hybrid":
        return "hybrid"
    return "rule"


def _reason_strings(reasons: dict[str, object]) -> tuple[str, ...]:
    """Flatten known rationale payload shapes into short strings."""
    values: list[str] = []
    for key in ("reasons", "rule_reasons", "rationale", "rationale_short", "llm_reason"):
        raw = reasons.get(key)
        if isinstance(raw, str) and raw:
            values.append(raw)
        elif isinstance(raw, list | tuple):
            values.extend(str(item) for item in raw if item)
    return tuple(values[:4])


def _summary_excerpt(
    *,
    repo: SummariesRepo,
    summary: Summary | None,
    user_id: UUID,
    fallback: str,
) -> str | None:
    """Return a short plaintext summary preview."""
    if summary is None:
        return fallback or None
    body = repo.decrypt_email_body(row=summary, user_id=user_id)
    text = " ".join(body.split())
    if len(text) <= 180:
        return text
    return text[:177].rstrip() + "..."


__all__ = ["router"]
