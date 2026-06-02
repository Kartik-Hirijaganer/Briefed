"""API tests for the accounts router.

Covers the Phase 1 e2e exit-criteria surface: a signed session cookie
grants access to ``/api/v1/accounts`` and a new connected account
appears in the list.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import db_session
from app.api.session import SESSION_COOKIE_NAME, sign_cookie
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.db.models import ConnectedAccount, Email, OAuthToken, SyncCursor, User
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


@pytest.mark.asyncio
async def test_list_accounts_returns_connected_rows(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    async with api_session() as session:
        user = User(email="me@x.com", tz="UTC", status="active")
        session.add(user)
        await session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email="me@x.com",
            status="active",
        )
        session.add(account)
        await session.commit()
        user_id = user.id

    cookie = sign_cookie({"user_id": str(user_id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/accounts",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["accounts"]) == 1
    assert payload["accounts"][0]["email"] == "me@x.com"
    assert payload["accounts"][0]["provider"] == "gmail"


@pytest.mark.asyncio
async def test_list_accounts_requires_cookie(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/accounts")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_account_scoped_to_owner(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    async with api_session() as session:
        owner = User(email="owner@x.com", tz="UTC", status="active")
        other = User(email="other@x.com", tz="UTC", status="active")
        session.add_all([owner, other])
        await session.flush()
        account = ConnectedAccount(
            user_id=other.id,
            provider="gmail",
            email="other@x.com",
            status="active",
        )
        session.add(account)
        await session.commit()
        owner_id, account_id = owner.id, account.id

    cookie = sign_cookie({"user_id": str(owner_id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/accounts/{account_id}",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_disconnect_account_revokes_local_access_and_keeps_row(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    async with api_session() as session:
        user = User(email="owner@x.com", tz="UTC", status="active")
        session.add(user)
        await session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email="owner@x.com",
            status="active",
        )
        session.add(account)
        await session.flush()
        session.add_all(
            [
                OAuthToken(
                    account_id=account.id,
                    access_token_ct=b"access",
                    refresh_token_ct=b"refresh",
                    scope=["https://www.googleapis.com/auth/gmail.readonly"],
                    expires_at=utcnow() + timedelta(hours=1),
                ),
                SyncCursor(
                    account_id=account.id,
                    history_id=123,
                    last_full_sync_at=utcnow(),
                    last_incremental_at=utcnow(),
                    stale=False,
                ),
                Email(
                    account_id=account.id,
                    gmail_message_id="m1",
                    thread_id="t1",
                    internal_date=utcnow(),
                    from_addr="sender@example.com",
                    subject="Hello",
                    snippet="Snippet",
                    content_hash=b"hash",
                ),
            ],
        )
        await session.commit()
        user_id, account_id = user.id, account.id

    cookie = sign_cookie({"user_id": str(user_id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/accounts/{account_id}/disconnect",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "revoked"
    assert payload["auto_scan_enabled"] is False
    assert payload["last_sync_at"] is None
    assert payload["emails_ingested_24h"] == 0

    async with api_session() as session:
        account = await session.get(ConnectedAccount, account_id)
        assert account is not None
        assert account.status == "revoked"
        assert account.auto_scan_enabled is False
        assert await session.get(SyncCursor, account_id) is None
        tokens = (
            await session.execute(select(OAuthToken).where(OAuthToken.account_id == account_id))
        ).scalars()
        emails = (
            await session.execute(select(Email).where(Email.account_id == account_id))
        ).scalars()
        assert tokens.first() is None
        assert emails.first() is None


@pytest.mark.asyncio
async def test_delete_account_requires_disconnect_first(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    async with api_session() as session:
        user = User(email="owner@x.com", tz="UTC", status="active")
        session.add(user)
        await session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email="owner@x.com",
            status="active",
        )
        session.add(account)
        await session.commit()
        user_id, account_id = user.id, account.id

    cookie = sign_cookie({"user_id": str(user_id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/accounts/{account_id}",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_delete_account_removes_revoked_account(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    async with api_session() as session:
        user = User(email="owner@x.com", tz="UTC", status="active")
        session.add(user)
        await session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email="owner@x.com",
            status="revoked",
        )
        session.add(account)
        await session.commit()
        user_id, account_id = user.id, account.id

    cookie = sign_cookie({"user_id": str(user_id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/accounts/{account_id}",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
    assert response.status_code == 204

    async with api_session() as session:
        assert await session.get(ConnectedAccount, account_id) is None


@pytest.mark.asyncio
async def test_logout_clears_browser_session_cookies(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert response.headers["clear-site-data"] == '"cache", "cookies", "storage"'
    cookies = response.headers.get_list("set-cookie")
    assert any(f"{SESSION_COOKIE_NAME}=" in cookie and "Max-Age=0" in cookie for cookie in cookies)
    assert any("briefed_oauth_state=" in cookie and "Max-Age=0" in cookie for cookie in cookies)
