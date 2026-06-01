"""Profile + schedule API (Track C — Phase II.3).

Routes:

* ``GET /api/v1/profile/me`` — current user's profile.
* ``PATCH /api/v1/profile/me`` — partial profile update (display name,
  aliases, legacy presidio toggle).
* ``GET /api/v1/profile/me/schedule`` — schedule view with a
  ``next_run_at_utc`` preview.
* ``PATCH /api/v1/profile/me/schedule`` — partial schedule update
  (cadence, times, timezone) with cross-field consistency validation.

Validation lives on the Pydantic models in
:mod:`app.schemas.profile`; the route bodies are thin wrappers over
SQLAlchemy mutations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import current_user_id, db_session
from app.api.errors import api_error_response
from app.core.clock import utcnow
from app.core.scheduling import UserScheduleView, next_slot_utc
from app.db.models import User
from app.schemas.emails import ErrorEnvelope
from app.schemas.profile import (
    UserProfileOut,
    UserProfilePatchRequest,
    UserScheduleOut,
    UserSchedulePatchRequest,
    _validate_frequency_consistency,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/profile", tags=["profile"])


async def _load_user(*, session: AsyncSession, user_id: UUID) -> User | None:
    """Load the caller's row when it exists.

    Args:
        session: Active async database session.
        user_id: Authenticated user id from the session cookie.

    Returns:
        User row, or ``None`` when the session points at a missing user.
    """
    return await session.get(User, user_id)


def _profile_out(user: User) -> UserProfileOut:
    """Map a SQLAlchemy ``User`` into the API response model."""
    return UserProfileOut(
        display_name=user.display_name,
        email_aliases=tuple(user.email_aliases or ()),
        redaction_aliases=tuple(user.redaction_aliases or ()),
        presidio_enabled=user.presidio_enabled,
        schedule_frequency=user.schedule_frequency,  # type: ignore[arg-type]
        schedule_times_local=tuple(user.schedule_times_local or ()),
        schedule_timezone=user.schedule_timezone,
    )


def _schedule_view_from_user(user: User) -> UserScheduleView:
    """Project the ``users`` row into the predicate's view."""
    return UserScheduleView(
        schedule_frequency=user.schedule_frequency,
        schedule_times_local=tuple(user.schedule_times_local or ()),
        schedule_timezone=user.schedule_timezone,
        last_run_finished_at=user.last_run_finished_at,
        current_run_id=user.current_run_id,
        current_run_started_at=user.current_run_started_at,
    )


def _schedule_out(user: User) -> UserScheduleOut:
    """Map a SQLAlchemy ``User`` into the schedule API response."""
    return UserScheduleOut(
        schedule_frequency=user.schedule_frequency,  # type: ignore[arg-type]
        schedule_times_local=tuple(user.schedule_times_local or ()),
        schedule_timezone=user.schedule_timezone,
        next_run_at_utc=next_slot_utc(utcnow(), _schedule_view_from_user(user)),
    )


@router.get(
    "/me",
    response_model=UserProfileOut,
    summary="Get the caller's profile",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_profile(
    request: Request,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> UserProfileOut | JSONResponse:
    """Return the caller's profile row."""
    user = await _load_user(session=session, user_id=user_id)
    if user is None:
        return api_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
            message="User not found.",
            request=request,
        )
    return _profile_out(user)


@router.patch(
    "/me",
    response_model=UserProfileOut,
    summary="Update the caller's profile",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def patch_profile(
    payload: UserProfilePatchRequest,
    request: Request,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> UserProfileOut | JSONResponse:
    """Apply a partial profile update.

    Args:
        payload: Validated patch body.
        request: Incoming request, used for error correlation.
        user_id: Authenticated caller, injected by :func:`current_user_id`.
        session: DB session.

    Returns:
        The fresh profile row after the update.
    """
    user = await _load_user(session=session, user_id=user_id)
    if user is None:
        return api_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
            message="User not found.",
            request=request,
        )
    updates = payload.model_dump(exclude_unset=True)
    if "display_name" in updates:
        user.display_name = updates["display_name"]
    if "email_aliases" in updates:
        aliases = updates["email_aliases"] or ()
        user.email_aliases = list(aliases)
    if "redaction_aliases" in updates:
        user.redaction_aliases = list(updates["redaction_aliases"] or ())
    if "presidio_enabled" in updates:
        user.presidio_enabled = bool(updates["presidio_enabled"])
    await session.flush()
    return _profile_out(user)


@router.get(
    "/me/schedule",
    response_model=UserScheduleOut,
    summary="Get the caller's schedule",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_schedule(
    request: Request,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> UserScheduleOut | JSONResponse:
    """Return cadence + times + a ``next_run_at_utc`` preview."""
    user = await _load_user(session=session, user_id=user_id)
    if user is None:
        return api_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
            message="User not found.",
            request=request,
        )
    return _schedule_out(user)


@router.patch(
    "/me/schedule",
    response_model=UserScheduleOut,
    summary="Update the caller's schedule",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorEnvelope},
    },
)
async def patch_schedule(
    payload: UserSchedulePatchRequest,
    request: Request,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> UserScheduleOut | JSONResponse:
    """Apply a partial schedule update with cross-field consistency.

    When the caller sends only one of ``schedule_frequency`` or
    ``schedule_times_local``, the cadence/slot-count invariant is
    re-checked against the existing row. Sending a frequency change
    without matching slots (or vice versa) returns 422.
    """
    user = await _load_user(session=session, user_id=user_id)
    if user is None:
        return api_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
            message="User not found.",
            request=request,
        )
    updates = payload.model_dump(exclude_unset=True)

    new_frequency = updates.get("schedule_frequency", user.schedule_frequency)
    raw_times = updates.get("schedule_times_local")
    new_times: tuple[str, ...] = (
        tuple(user.schedule_times_local or ()) if raw_times is None else tuple(raw_times)
    )
    try:
        _validate_frequency_consistency(new_frequency, new_times)
    except ValueError as exc:
        return api_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="schedule_inconsistent",
            message=str(exc),
            request=request,
            details={"field": "schedule_frequency"},
        )

    if "schedule_frequency" in updates:
        user.schedule_frequency = updates["schedule_frequency"]
    if "schedule_times_local" in updates:
        user.schedule_times_local = list(updates["schedule_times_local"] or ())
    if "schedule_timezone" in updates:
        user.schedule_timezone = updates["schedule_timezone"]
    await session.flush()
    return _schedule_out(user)


__all__ = ["router"]
