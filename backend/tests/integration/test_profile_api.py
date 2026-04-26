"""Integration tests for the Track C profile + schedule API."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import db_session
from app.api.session import SESSION_COOKIE_NAME, sign_cookie
from app.core.config import Settings, get_settings
from app.db.models import User
from app.main import app


@pytest_asyncio.fixture()
async def api_session(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def _settings() -> Settings:
        return Settings(
            env="test",
            runtime="local",
            log_level="info",
            session_signing_key="test-key",
        )

    app.dependency_overrides[db_session] = _override
    app.dependency_overrides[get_settings] = _settings
    try:
        yield factory
    finally:
        app.dependency_overrides.clear()


async def _seed_user(api_session: async_sessionmaker[AsyncSession]) -> User:
    async with api_session() as session:
        user = User(email="me@x.com", tz="UTC", status="active")
        session.add(user)
        await session.commit()
        return user


async def test_get_profile_returns_defaults(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/profile/me",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] is None
    assert body["schedule_frequency"] == "once_daily"
    assert body["schedule_times_local"] == ["08:00"]
    assert body["theme_preference"] == "system"


async def test_patch_profile_updates_fields(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/profile/me",
            cookies={SESSION_COOKIE_NAME: cookie},
            json={
                "display_name": "Kartik",
                "email_aliases": ["alt@example.com"],
                "redaction_aliases": ["codename"],
                "presidio_enabled": False,
                "theme_preference": "dark",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "Kartik"
    assert body["email_aliases"] == ["alt@example.com"]
    assert body["redaction_aliases"] == ["codename"]
    assert body["presidio_enabled"] is False
    assert body["theme_preference"] == "dark"


async def test_get_schedule_returns_next_run(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/profile/me/schedule",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schedule_frequency"] == "once_daily"
    # next_run_at_utc may be null only when the schedule is disabled.
    assert body["next_run_at_utc"] is not None


async def test_patch_schedule_rejects_inconsistent_payload(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/profile/me/schedule",
            cookies={SESSION_COOKIE_NAME: cookie},
            json={"schedule_frequency": "twice_daily"},
        )
    # Existing single-slot row + cadence change → consistency error.
    assert response.status_code == 422


async def test_patch_schedule_accepts_valid_change(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/profile/me/schedule",
            cookies={SESSION_COOKIE_NAME: cookie},
            json={
                "schedule_frequency": "twice_daily",
                "schedule_times_local": ["08:00", "18:00"],
                "schedule_timezone": "America/New_York",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schedule_frequency"] == "twice_daily"
    assert body["schedule_times_local"] == ["08:00", "18:00"]
    assert body["schedule_timezone"] == "America/New_York"
