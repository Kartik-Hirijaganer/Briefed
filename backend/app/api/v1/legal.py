"""Legal-consent API.

Routes:

* ``GET /api/v1/legal/consent`` — current user's consent status.
* ``POST /api/v1/legal/consent`` — accept the current privacy policy and
  terms of service versions.

The consent status endpoint is the authenticated probe used by the frontend
gate before any Gmail-derived app route mounts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import current_user_id, db_session
from app.api.errors import api_error_response
from app.core.clock import utcnow
from app.core.consent import (
    CURRENT_PRIVACY_POLICY_VERSION,
    CURRENT_TERMS_VERSION,
    has_current_legal_consent,
)
from app.db.models import User
from app.schemas.emails import ErrorEnvelope
from app.schemas.legal import LegalConsentRequest, LegalConsentStatusOut

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/legal", tags=["legal"])


async def _load_user(*, session: AsyncSession, user_id: UUID) -> User | None:
    """Load the caller's row when it exists.

    Args:
        session: Active async database session.
        user_id: Authenticated user id from the session cookie.

    Returns:
        User row, or ``None`` when the session points at a missing user.
    """
    return await session.get(User, user_id)


def _status_out(user: User) -> LegalConsentStatusOut:
    """Map a user row into the legal-consent response model.

    Args:
        user: Account owner row.

    Returns:
        Current legal-consent status for ``user``.
    """
    return LegalConsentStatusOut(
        current_privacy_policy_version=CURRENT_PRIVACY_POLICY_VERSION,
        current_terms_version=CURRENT_TERMS_VERSION,
        accepted_privacy_policy_version=user.privacy_policy_version_accepted,
        accepted_terms_version=user.terms_version_accepted,
        consent_required=not has_current_legal_consent(user),
        accepted_at=user.legal_accepted_at,
    )


@router.get(
    "/consent",
    response_model=LegalConsentStatusOut,
    summary="Get the caller's legal-consent status",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_legal_consent(
    request: Request,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> LegalConsentStatusOut | JSONResponse:
    """Return whether the caller must accept current legal policies.

    Args:
        request: Incoming request, used for error correlation.
        user_id: Authenticated caller, injected by :func:`current_user_id`.
        session: DB session.

    Returns:
        Current legal-consent status, or a 404 error envelope when the
        authenticated user row no longer exists.
    """
    user = await _load_user(session=session, user_id=user_id)
    if user is None:
        return api_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
            message="User not found.",
            request=request,
        )
    return _status_out(user)


@router.post(
    "/consent",
    response_model=LegalConsentStatusOut,
    summary="Accept the current legal policies",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorEnvelope},
    },
)
async def accept_legal_consent(
    payload: LegalConsentRequest,
    request: Request,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> LegalConsentStatusOut | JSONResponse:
    """Record acceptance of the current legal policy versions.

    Args:
        payload: Policy versions the user saw and accepted.
        request: Incoming request, used for error correlation and user-agent capture.
        user_id: Authenticated caller, injected by :func:`current_user_id`.
        session: DB session.

    Returns:
        Updated legal-consent status, or an error envelope for missing users
        or stale/mismatched policy versions.
    """
    if (
        payload.privacy_policy_version != CURRENT_PRIVACY_POLICY_VERSION
        or payload.terms_version != CURRENT_TERMS_VERSION
    ):
        return api_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="consent_version_mismatch",
            message="Consent versions must match the current policies.",
            request=request,
            details={
                "current_privacy_policy_version": CURRENT_PRIVACY_POLICY_VERSION,
                "current_terms_version": CURRENT_TERMS_VERSION,
            },
        )

    user = await _load_user(session=session, user_id=user_id)
    if user is None:
        return api_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="user_not_found",
            message="User not found.",
            request=request,
        )

    user.privacy_policy_version_accepted = CURRENT_PRIVACY_POLICY_VERSION
    user.terms_version_accepted = CURRENT_TERMS_VERSION
    user.legal_accepted_at = utcnow()
    user.legal_accepted_user_agent = request.headers.get("user-agent")
    await session.flush()
    return _status_out(user)


__all__ = ["router"]
