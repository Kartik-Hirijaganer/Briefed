"""Tests for async database session engine construction."""

from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool

from app.db import session as db_session


def test_resolve_async_url_converts_plain_postgres_url() -> None:
    """Ensure plain Postgres URLs are normalized to the asyncpg dialect."""
    assert (
        db_session._resolve_async_url("postgresql://user:pass@example.test/postgres")
        == "postgresql+asyncpg://user:pass@example.test/postgres"
    )


def test_build_engine_disables_asyncpg_statement_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure Supabase pgbouncer connections do not use prepared statements."""
    captured: dict[str, Any] = {}
    sentinel = cast(AsyncEngine, object())

    def _fake_create_async_engine(url: str, **kwargs: Any) -> AsyncEngine:
        """Capture engine construction options.

        Args:
            url: SQLAlchemy database URL.
            **kwargs: Engine options passed by the session module.

        Returns:
            Sentinel async engine.
        """
        captured["url"] = url
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(db_session, "create_async_engine", _fake_create_async_engine)

    engine = db_session._build_engine("postgresql+asyncpg://user:pass@example.test/postgres")

    assert engine is sentinel
    assert captured["connect_args"] == {"statement_cache_size": 0}
    assert captured["poolclass"] is NullPool
    assert captured["pool_pre_ping"] is True
    assert captured["future"] is True
