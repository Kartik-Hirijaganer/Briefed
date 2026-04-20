"""Shared pytest fixtures for the Briefed backend tests.

The in-memory SQLite fixture creates the ORM schema via
``Base.metadata.create_all`` (plan Phase 1 uses ``alembic upgrade head``
in production; tests stay on SQLite so they run without docker-compose).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.models import Base


@pytest_asyncio.fixture()
async def test_engine() -> AsyncIterator[AsyncEngine]:
    """Async SQLite engine with the Phase 1 schema created."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def test_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield a fresh :class:`AsyncSession` bound to the test engine."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
