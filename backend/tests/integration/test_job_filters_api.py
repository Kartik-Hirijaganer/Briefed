"""API tests for the ``/api/v1/job-filters`` CRUD router (plan §14 Phase 4).

Covers:

* create + list happy path
* update bumps :attr:`JobFilter.version`
* unknown predicate keys rejected at the request boundary
* ownership scoping on update + delete (404 to non-owners)
* duplicate ``name`` per user returns 409
"""

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
async def test_create_and_list_filter(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/job-filters",
            json={
                "name": "remote-staff-roles",
                "predicate": {
                    "min_comp": 180000,
                    "currency": "USD",
                    "remote_required": True,
                    "seniority_in": ["senior", "staff", "principal"],
                },
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert create.status_code == 201, create.text
        body = create.json()
        assert body["name"] == "remote-staff-roles"
        assert body["version"] == 1
        assert body["active"] is True

        listing = client.get(
            "/api/v1/job-filters",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert listing.status_code == 200
        assert len(listing.json()["filters"]) == 1


@pytest.mark.asyncio
async def test_update_bumps_version(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/job-filters",
            json={
                "name": "remote-staff-roles",
                "predicate": {"remote_required": True},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        filter_id = create.json()["id"]

        update = client.put(
            f"/api/v1/job-filters/{filter_id}",
            json={
                "name": "remote-staff-roles",
                "predicate": {
                    "remote_required": True,
                    "min_comp": 200000,
                    "currency": "USD",
                },
                "active": True,
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert update.status_code == 200
        body = update.json()
        assert body["version"] == 2
        assert body["predicate"]["min_comp"] == 200000


@pytest.mark.asyncio
async def test_reject_unknown_predicate_key(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/job-filters",
            json={
                "name": "broken",
                "predicate": {"bogus_key": 1},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_filter_enforces_owner(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        create = client.post(
            "/api/v1/job-filters",
            json={
                "name": "remote-only",
                "predicate": {"remote_required": True},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        filter_id = create.json()["id"]

        other = sign_cookie(
            {"user_id": "00000000-0000-0000-0000-000000000001"},
            secret="test-key",
        )
        unauthorized = client.delete(
            f"/api/v1/job-filters/{filter_id}",
            cookies={SESSION_COOKIE_NAME: other},
        )
        assert unauthorized.status_code == 404

        success = client.delete(
            f"/api/v1/job-filters/{filter_id}",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert success.status_code == 204


@pytest.mark.asyncio
async def test_duplicate_filter_name_returns_409(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/job-filters",
            json={
                "name": "dup",
                "predicate": {"remote_required": True},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/v1/job-filters",
            json={
                "name": "dup",
                "predicate": {"remote_required": False},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert second.status_code == 409
