"""``/api/v1/job-filters`` router — CRUD over the user's job-filter predicates.

Each mutation bumps :attr:`app.db.models.JobFilter.version` so the next
job-extract worker run snapshots the new version onto downstream
:attr:`app.db.models.JobMatch.filter_version` writes — a filter change
never retroactively re-labels historical matches (plan §14 Phase 4).

Predicate validation runs at the request boundary via
:class:`app.schemas.jobs.JobFilterIn` so a malformed clause is a 422
before the row is persisted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import current_user_id, db_session
from app.db.models import JobFilter
from app.schemas.jobs import (
    JobFilterIn,
    JobFilterOut,
    JobFiltersListResponse,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/job-filters", tags=["job-filters"])


@router.get(
    "",
    response_model=JobFiltersListResponse,
    summary="List job filters",
)
async def list_filters(
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> JobFiltersListResponse:
    """Return every filter the authenticated user owns.

    Args:
        user_id: Authenticated owner.
        session: Active async session.

    Returns:
        :class:`JobFiltersListResponse` ordered by ``created_at ASC``.
    """
    rows = (
        (
            await session.execute(
                select(JobFilter)
                .where(JobFilter.user_id == user_id)
                .order_by(JobFilter.created_at, JobFilter.id),
            )
        )
        .scalars()
        .all()
    )
    return JobFiltersListResponse(
        filters=tuple(JobFilterOut.model_validate(row) for row in rows),
    )


@router.post(
    "",
    response_model=JobFilterOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a job filter",
)
async def create_filter(
    payload: JobFilterIn,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> JobFilterOut:
    """Insert a new filter for the authenticated user.

    Args:
        payload: Validated request body.
        user_id: Authenticated owner.
        session: Active async session.

    Returns:
        The created :class:`JobFilterOut`.

    Raises:
        HTTPException: 409 when ``name`` already exists for the user.
    """
    row = JobFilter(
        user_id=user_id,
        name=payload.name,
        predicate=payload.predicate,
        version=1,
        active=payload.active,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"filter named {payload.name!r} already exists",
        ) from exc
    await session.refresh(row)
    return JobFilterOut.model_validate(row)


@router.put(
    "/{filter_id}",
    response_model=JobFilterOut,
    summary="Replace a job filter",
)
async def update_filter(
    filter_id: UUID,
    payload: JobFilterIn,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> JobFilterOut:
    """Replace ``filter_id``'s predicate + active flag, bumping ``version``.

    Args:
        filter_id: Target filter.
        payload: Validated request body.
        user_id: Authenticated owner.
        session: Active async session.

    Returns:
        The updated :class:`JobFilterOut`.

    Raises:
        HTTPException: 404 when the filter does not belong to the caller.
        HTTPException: 409 when the rename collides with another filter.
    """
    row = await session.get(JobFilter, filter_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="filter not found")
    row.name = payload.name
    row.predicate = payload.predicate
    row.active = payload.active
    row.version = row.version + 1
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"filter named {payload.name!r} already exists",
        ) from exc
    await session.refresh(row)
    return JobFilterOut.model_validate(row)


@router.delete(
    "/{filter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a job filter",
)
async def delete_filter(
    filter_id: UUID,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Hard-delete ``filter_id``.

    Args:
        filter_id: Target filter.
        user_id: Authenticated owner.
        session: Active async session.

    Raises:
        HTTPException: 404 when the filter does not belong to the caller.
    """
    row = await session.get(JobFilter, filter_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="filter not found")
    await session.delete(row)


__all__ = ["router"]
