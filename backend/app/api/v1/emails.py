"""``/api/v1/emails`` router for bucket lists and user overrides."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select

from app.api.deps import current_user_id, db_session
from app.core.config import Settings, get_settings
from app.db.models import Classification, ConnectedAccount, Email, Summary
from app.schemas.emails import (
    DecisionSource,
    EmailBucket,
    EmailBucketPatchRequest,
    EmailRowOut,
    EmailsListResponse,
)
from app.services.classification.repository import ClassificationsRepo, ClassificationWrite
from app.services.summarization.repository import SummariesRepo

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import KmsClient


router = APIRouter(prefix="/emails", tags=["emails"])

_PRIMARY_BUCKETS: tuple[EmailBucket, ...] = ("must_read", "good_to_read", "ignore", "waste")
"""Buckets the PWA renders as email lists."""


def _classifications_repo_for(settings: Settings) -> ClassificationsRepo:
    """Return a classification repo wired to KMS when configured."""
    if not settings.content_key_alias:
        return ClassificationsRepo(cipher=None)
    import boto3  # type: ignore[import-untyped]

    from app.core.security import EnvelopeCipher

    return ClassificationsRepo(
        cipher=EnvelopeCipher(
            key_id=settings.content_key_alias,
            client=cast("KmsClient", boto3.client("kms")),
        ),
    )


def _summaries_repo_for(settings: Settings) -> SummariesRepo:
    """Return a summaries repo wired to KMS when configured."""
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


@router.get("", response_model=EmailsListResponse, summary="List classified emails")
async def list_emails(
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
    bucket: EmailBucket | None = Query(default=None),
    account_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> EmailsListResponse:
    """Return classified email rows for the PWA.

    Args:
        user_id: Authenticated owner.
        session: Active async session.
        settings: Cached app settings.
        bucket: Optional primary bucket filter.
        account_id: Optional account filter.
        limit: Maximum row count.

    Returns:
        Newest-first rows plus total count.
    """
    base_filters = [
        ConnectedAccount.user_id == user_id,
        Classification.label.in_(_PRIMARY_BUCKETS),
    ]
    if bucket is not None:
        base_filters.append(Classification.label == bucket)
    if account_id is not None:
        base_filters.append(ConnectedAccount.id == account_id)

    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Email)
                .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
                .join(Classification, Classification.email_id == Email.id)
                .where(*base_filters),
            )
        ).scalar_one()
        or 0
    )

    rows = (
        await session.execute(
            select(Email, ConnectedAccount, Classification, Summary)
            .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
            .join(Classification, Classification.email_id == Email.id)
            .outerjoin(
                Summary,
                and_(Summary.email_id == Email.id, Summary.kind == "email"),
            )
            .where(*base_filters)
            .order_by(Email.internal_date.desc())
            .limit(limit),
        )
    ).all()

    classification_repo = _classifications_repo_for(settings)
    summary_repo = _summaries_repo_for(settings)
    return EmailsListResponse(
        emails=tuple(
            _row_out(
                email=email,
                account=account,
                classification=classification,
                summary=summary,
                user_id=user_id,
                classification_repo=classification_repo,
                summary_repo=summary_repo,
            )
            for email, account, classification, summary in rows
        ),
        total=total,
    )


@router.patch(
    "/{email_id}/bucket",
    response_model=EmailRowOut,
    summary="Update a user-selected email bucket",
)
async def patch_email_bucket(
    email_id: UUID,
    body: EmailBucketPatchRequest,
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> EmailRowOut:
    """Persist a user override from swipe gestures or queued replay.

    Args:
        email_id: Target email.
        body: Destination bucket.
        user_id: Authenticated owner.
        session: Active async session.
        settings: Cached app settings.

    Returns:
        Updated email row.

    Raises:
        HTTPException: 404 when the email does not belong to the caller.
    """
    owned = (
        await session.execute(
            select(Email, ConnectedAccount, Classification, Summary)
            .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
            .outerjoin(Classification, Classification.email_id == Email.id)
            .outerjoin(
                Summary,
                and_(Summary.email_id == Email.id, Summary.kind == "email"),
            )
            .where(Email.id == email_id, ConnectedAccount.user_id == user_id),
        )
    ).first()
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="email not found")

    email, account, _classification, summary = owned
    classification_repo = _classifications_repo_for(settings)
    await classification_repo.upsert(
        session,
        ClassificationWrite(
            email_id=email.id,
            label=body.bucket,
            score=Decimal("1.000"),
            rubric_version=0,
            prompt_version_id=None,
            decision_source="rule",
            model="user_override",
            tokens_in=0,
            tokens_out=0,
            is_newsletter=False,
            is_job_candidate=False,
            reasons={"reasons": ["User moved this email in the PWA."]},
            user_id=user_id,
        ),
    )
    classification = (
        (
            await session.execute(
                select(Classification).where(Classification.email_id == email.id),
            )
        )
        .scalars()
        .one()
    )
    return _row_out(
        email=email,
        account=account,
        classification=classification,
        summary=summary,
        user_id=user_id,
        classification_repo=classification_repo,
        summary_repo=_summaries_repo_for(settings),
    )


def _row_out(
    *,
    email: Email,
    account: ConnectedAccount,
    classification: Classification,
    summary: Summary | None,
    user_id: UUID,
    classification_repo: ClassificationsRepo,
    summary_repo: SummariesRepo,
) -> EmailRowOut:
    """Convert ORM rows to the frontend email-row contract."""
    return EmailRowOut(
        id=email.id,
        account_email=account.email,
        thread_id=email.thread_id,
        subject=email.subject,
        sender=email.from_addr,
        received_at=email.internal_date,
        bucket=cast(EmailBucket, classification.label),
        confidence=float(classification.score),
        decision_source=_decision_source(classification.decision_source),
        reasons=_reasons_from(
            classification_repo.decrypt_reasons(row=classification, user_id=user_id),
        ),
        summary_excerpt=_summary_excerpt(summary=summary, user_id=user_id, repo=summary_repo),
    )


def _decision_source(source: str) -> DecisionSource:
    """Map persisted source names onto frontend vocabulary."""
    if source == "model":
        return "llm"
    if source == "hybrid":
        return "hybrid"
    return "rule"


def _reasons_from(payload: dict[str, Any]) -> tuple[str, ...]:
    """Extract displayable reasons from a decrypted rationale payload."""
    for key in ("reasons", "reason", "rationale", "rationale_short"):
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(str(item) for item in value if str(item).strip())
        if isinstance(value, str) and value.strip():
            return (value.strip(),)
    return ("No rationale captured.",)


def _summary_excerpt(
    *,
    summary: Summary | None,
    user_id: UUID,
    repo: SummariesRepo,
) -> str | None:
    """Return a short plaintext summary preview when one exists."""
    if summary is None:
        return None
    body = repo.decrypt_email_body(row=summary, user_id=user_id).replace("\n", " ").strip()
    if not body:
        return None
    return body if len(body) <= 180 else f"{body[:177]}..."
