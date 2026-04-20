"""FastAPI dependencies shared across v1 routers.

The session dependency is a thin wrapper around
:mod:`app.api.session`: it extracts ``briefed_session``, verifies its
HMAC, and returns the decoded payload. Routers that need the caller's
``user_id`` depend on :func:`current_user_id`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, status

from app.api.session import SESSION_COOKIE_NAME, verify_cookie
from app.core.config import Settings, get_settings
from app.core.errors import AuthError
from app.db.session import get_sessionmaker

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


async def db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a committed async session per request.

    Yields:
        A short-lived :class:`AsyncSession`. Commits on success, rolls
        back on exceptions.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def current_user_id(
    cookie_value: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
) -> UUID:
    """Extract ``user_id`` from the signed session cookie.

    Args:
        cookie_value: Raw cookie string; FastAPI injects it via the
            :class:`fastapi.Cookie` marker.
        settings: Cached :class:`Settings`.

    Returns:
        The caller's ``user_id`` as a UUID.

    Raises:
        HTTPException: 401 when the cookie is missing, tampered, or
            unsigned (no ``session_signing_key`` configured).
    """
    if not cookie_value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    if not settings.session_signing_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="session signing key not configured",
        )
    try:
        payload = verify_cookie(cookie_value, secret=settings.session_signing_key)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user_id = payload.get("user_id")
    if not isinstance(user_id, str):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad session payload")
    try:
        return UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad user id") from exc
