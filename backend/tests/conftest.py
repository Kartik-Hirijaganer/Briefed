"""Shared pytest fixtures for the Briefed backend tests.

The in-memory SQLite fixture creates the ORM schema via
``Base.metadata.create_all`` (plan Phase 1 uses ``alembic upgrade head``
in production; tests stay on SQLite so they run without docker-compose).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.models import Base


# Tests assume KMS aliases + AWS creds are unset, matching CI's environment.
# Locally, ``.env`` populates these and ``~/.aws/credentials`` supplies creds,
# which routes integration tests through real KMS instead of the unset-alias
# fallback paths. Empty strings beat the ``.env`` values because
# ``pydantic-settings`` reads env vars *after* the env_file. CI never sets
# these, so the fixture is a no-op there.
_POLLUTED_ENV_VARS: tuple[str, ...] = (
    "BRIEFED_TOKEN_WRAP_KEY_ALIAS",
    "BRIEFED_CONTENT_KEY_ALIAS",
    "AWS_PROFILE",
)


@pytest.fixture(autouse=True, scope="session")
def _scrub_local_env_pollution() -> Iterator[None]:
    """Override developer ``.env`` values that diverge from CI defaults."""
    snapshot = {key: os.environ.get(key) for key in _POLLUTED_ENV_VARS}
    for key in _POLLUTED_ENV_VARS:
        if key.startswith("AWS_"):
            os.environ.pop(key, None)
        else:
            os.environ[key] = ""
    try:
        yield
    finally:
        for key, value in snapshot.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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
