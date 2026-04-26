"""API tests for the rubric CRUD router (plan §14 Phase 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
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


async def _seed_user(factory: async_sessionmaker[AsyncSession]) -> User:
    async with factory() as session:
        user = User(email="me@x.com", tz="UTC", status="active")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_create_and_list_rule(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/rubric",
            json={
                "priority": 500,
                "match": {"from_domain": "bigcorp.example"},
                "action": {
                    "label": "must_read",
                    "confidence": 0.92,
                    "reasons": ["boss"],
                },
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert create.status_code == 201, create.text
        created = create.json()
        assert created["priority"] == 500
        assert created["version"] == 1

        listing = client.get(
            "/api/v1/rubric",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert listing.status_code == 200
        assert len(listing.json()["rules"]) == 1


@pytest.mark.asyncio
async def test_update_bumps_version(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/rubric",
            json={
                "priority": 100,
                "match": {"from_domain": "bigcorp.example"},
                "action": {"label": "good_to_read", "confidence": 0.8},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        rule_id = create.json()["id"]

        update = client.put(
            f"/api/v1/rubric/{rule_id}",
            json={
                "priority": 900,
                "match": {"from_domain": "bigcorp.example"},
                "action": {"label": "must_read", "confidence": 0.95},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert update.status_code == 200
        assert update.json()["priority"] == 900
        assert update.json()["version"] == 2
        assert update.json()["action"]["label"] == "must_read"


@pytest.mark.asyncio
async def test_reject_unknown_match_key(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/rubric",
            json={
                "priority": 1,
                "match": {"bogus": 1},
                "action": {"label": "must_read", "confidence": 0.9},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_rule_enforces_owner(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/rubric",
            json={
                "priority": 10,
                "match": {"from_domain": "bigcorp.example"},
                "action": {"label": "good_to_read", "confidence": 0.8},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        rule_id = create.json()["id"]

        other_cookie = sign_cookie(
            {"user_id": "00000000-0000-0000-0000-000000000001"},
            secret="test-key",
        )
        unauthorized = client.delete(
            f"/api/v1/rubric/{rule_id}",
            cookies={SESSION_COOKIE_NAME: other_cookie},
        )
        assert unauthorized.status_code == 404

        success = client.delete(
            f"/api/v1/rubric/{rule_id}",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert success.status_code == 204
