"""Session-auth endpoints for browser session lifecycle operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.api.session import OAUTH_STATE_COOKIE_NAME, SESSION_COOKIE_NAME
from app.core.config import Settings, get_settings

CSRF_COOKIE_NAME = "briefed_csrf"
"""Readable double-submit CSRF cookie mirrored by the frontend client."""

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
def logout(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> None:
    """Clear Briefed auth cookies and request browser-side site-data cleanup.

    Args:
        response: Mutable FastAPI response used to expire cookies and set
            browser cleanup headers.
        settings: Cached app settings, used to mirror the runtime's cookie
            security flags.

    Returns:
        None.
    """
    secure = settings.runtime != "local"
    response.delete_cookie(SESSION_COOKIE_NAME, secure=secure, samesite="lax")
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME, secure=secure, samesite="lax")
    response.delete_cookie(CSRF_COOKIE_NAME, secure=secure, samesite="lax")
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
