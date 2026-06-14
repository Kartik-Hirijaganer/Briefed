"""Legal consent helpers shared by API routes and workers.

The current privacy and terms versions are backend-owned because backend
processing must be able to reject Gmail-derived work even when a client is stale
or bypassed. Frontend legal content mirrors these constants.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.db.models import User

CURRENT_PRIVACY_POLICY_VERSION = 1
"""Current privacy policy version required for Gmail data processing."""

CURRENT_TERMS_VERSION = 1
"""Current terms of service version required for Gmail data processing."""


def has_current_legal_consent(user: User) -> bool:
    """Return whether ``user`` accepted the current legal terms.

    Args:
        user: Account owner row to inspect.

    Returns:
        ``True`` when both accepted legal versions are current.
    """
    return (
        user.privacy_policy_version_accepted >= CURRENT_PRIVACY_POLICY_VERSION
        and user.terms_version_accepted >= CURRENT_TERMS_VERSION
    )


def enforce_legal_consent(user: User) -> None:
    """Reject Gmail data processing when legal consent is stale or absent.

    Args:
        user: Account owner row to inspect.

    Raises:
        HTTPException: ``451`` when current legal consent is required.
    """
    if not has_current_legal_consent(user):
        raise HTTPException(
            status_code=status.HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS,
            detail="legal_consent_required",
        )


__all__ = [
    "CURRENT_PRIVACY_POLICY_VERSION",
    "CURRENT_TERMS_VERSION",
    "enforce_legal_consent",
    "has_current_legal_consent",
]
