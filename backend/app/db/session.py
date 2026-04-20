"""Async SQLAlchemy engine + session factory (plan §19.15).

Lambda warm-window reuse is explicitly disabled: the Supabase
transaction-mode pooler multiplexes connections for us, and a persistent
SQLAlchemy pool across Lambda invocations causes the pooler to see stale
connections. ``NullPool`` + per-request checkout is the safe default.

The engine is lazily constructed on first use so importing this module
at Lambda cold-start time does not open a connection before secrets are
hydrated. A single cached engine is reused for the rest of the warm
window.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator


_engine: AsyncEngine | None = None
"""Process-level cache of the async engine."""

_sessionmaker: async_sessionmaker[AsyncSession] | None = None
"""Process-level cache of the session factory."""


def _resolve_async_url(raw: str) -> str:
    """Normalize a raw DB URL to the asyncpg driver.

    Both Supabase (``postgresql://``) and the Phase 0 ``.env`` convention
    (``postgresql+asyncpg://``) land here; this helper force-selects the
    asyncpg driver so the engine never silently picks up psycopg2.

    Args:
        raw: The configured DB URL.

    Returns:
        A SQLAlchemy-compatible async URL.
    """
    if raw.startswith("postgresql+asyncpg://"):
        return raw
    if raw.startswith("postgresql://"):
        return "postgresql+asyncpg://" + raw[len("postgresql://") :]
    return raw


def _build_engine(url: str) -> AsyncEngine:
    """Construct a fresh async engine tuned for Lambda.

    Args:
        url: Async-dialect DB URL.

    Returns:
        A :class:`AsyncEngine` with ``NullPool`` (no cross-invocation reuse).
    """
    return create_async_engine(
        url,
        poolclass=NullPool,
        pool_pre_ping=True,
        future=True,
    )


def get_engine() -> AsyncEngine:
    """Return the shared async engine, building it on first use.

    Returns:
        The cached :class:`AsyncEngine`.

    Raises:
        RuntimeError: If ``settings.database_url`` is not configured.
    """
    global _engine  # noqa: PLW0603 — deliberate module-level cache
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError(
                "database_url is not configured. Set BRIEFED_DATABASE_URL or "
                "the corresponding SSM parameter before opening a session.",
            )
        _engine = _build_engine(_resolve_async_url(settings.database_url))
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the shared session factory, building it on first use.

    Returns:
        A :class:`async_sessionmaker` producing :class:`AsyncSession`.
    """
    global _sessionmaker  # noqa: PLW0603
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker


async def session_scope() -> AsyncIterator[AsyncSession]:
    """Async generator yielding a session with commit/rollback semantics.

    Usage:

    .. code-block:: python

        async for session in session_scope():
            session.add(user)

    Yields:
        A short-lived :class:`AsyncSession`. Commits on normal exit,
        rolls back on exceptions, and always closes the connection.
    """
    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def reset_engine() -> None:
    """Drop the cached engine + session factory.

    Used by tests to force re-creation after monkeypatching
    ``settings.database_url``.
    """
    global _engine, _sessionmaker  # noqa: PLW0603
    _engine = None
    _sessionmaker = None
