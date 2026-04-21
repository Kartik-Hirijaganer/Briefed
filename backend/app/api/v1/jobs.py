"""``/api/v1/jobs`` router — read-only listing of curated job matches.

Exposes the rows that the Phase 4 worker pipeline writes to
``job_matches``. The default response is the curated list — only rows
where ``passed_filter=True`` and ``match_score >= 0.7`` (the digest
floor; see :mod:`app.services.jobs.extractor`). Callers can pass
``include_filtered=true`` to inspect rows the active filters rejected,
which powers the triage page's "does not match your filters" badge.

The router decrypts :attr:`app.db.models.JobMatch.match_reason_ct` via
:class:`app.services.jobs.repository.JobMatchesRepo` so the response
body never carries ciphertext. The decrypt path is wrapped in a
content cipher when ``settings.content_key_alias`` is configured;
local + test environments fall back to the pass-through repo mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import current_user_id, db_session
from app.core.config import Settings, get_settings
from app.db.models import ConnectedAccount, Email, JobMatch
from app.schemas.jobs import JobMatchesListResponse, JobMatchOut
from app.services.jobs.repository import JobMatchesRepo

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import KmsClient


router = APIRouter(prefix="/jobs", tags=["jobs"])

_DIGEST_CONFIDENCE_FLOOR = 0.7
"""Mirror of ``app.services.jobs.extractor._PASSED_FILTER_CONFIDENCE_FLOOR``."""


@router.get(
    "",
    response_model=JobMatchesListResponse,
    summary="List curated job matches",
)
async def list_job_matches(
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
    include_filtered: bool = Query(
        default=False,
        description=(
            "When true, include rows whose active-filter evaluation"
            " failed or whose confidence is below the digest floor."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> JobMatchesListResponse:
    """Return job matches the caller owns.

    Args:
        user_id: Authenticated owner.
        session: Active async session.
        settings: Cached :class:`Settings`.
        include_filtered: Override the curated default.
        limit: Maximum rows to return.

    Returns:
        :class:`JobMatchesListResponse` with newest matches first.
    """
    stmt = (
        select(JobMatch)
        .join(Email, Email.id == JobMatch.email_id)
        .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
        .where(ConnectedAccount.user_id == user_id)
        .order_by(JobMatch.created_at.desc())
        .limit(limit)
    )
    if not include_filtered:
        stmt = stmt.where(
            JobMatch.passed_filter.is_(True),
            JobMatch.match_score >= _DIGEST_CONFIDENCE_FLOOR,
        )
    rows = (await session.execute(stmt)).scalars().all()

    repo = JobMatchesRepo(cipher=None)
    if settings.content_key_alias:
        import boto3  # type: ignore[import-untyped]

        from app.core.security import EnvelopeCipher

        repo = JobMatchesRepo(
            cipher=EnvelopeCipher(
                key_id=settings.content_key_alias,
                client=cast("KmsClient", boto3.client("kms")),
            ),
        )

    matches = tuple(
        JobMatchOut(
            id=row.id,
            email_id=row.email_id,
            title=row.title,
            company=row.company,
            location=row.location,
            remote=row.remote,
            comp_min=row.comp_min,
            comp_max=row.comp_max,
            currency=row.currency,
            seniority=row.seniority,
            source_url=row.source_url,
            match_score=row.match_score,
            filter_version=row.filter_version,
            passed_filter=row.passed_filter,
            match_reason=repo.decrypt_reason(row=row, user_id=user_id),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    )
    return JobMatchesListResponse(matches=matches)


__all__ = ["router"]
