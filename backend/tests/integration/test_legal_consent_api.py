"""Integration tests for the legal-consent API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import db_session
from app.api.session import SESSION_COOKIE_NAME, sign_cookie
from app.core.config import Settings, get_settings
from app.core.consent import CURRENT_PRIVACY_POLICY_VERSION, CURRENT_TERMS_VERSION
from app.db.models import User
from app.main import app


@pytest_asyncio.fixture()
async def api_session(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Override app DB/settings dependencies for legal API integration tests.

    Args:
        test_engine: In-memory SQLite engine from the shared fixture.

    Yields:
        Async sessionmaker used by both the app dependency and test seed helpers.
    """
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override() -> AsyncIterator[AsyncSession]:
        """Yield a committed API session bound to the test engine.

        Yields:
            Async database session for one request.
        """
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def _settings() -> Settings:
        """Return deterministic settings for signed test cookies.

        Returns:
            Test settings with a fixed session signing key.
        """
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


async def _seed_user(
    api_session: async_sessionmaker[AsyncSession],
    *,
    accepted: bool = False,
) -> User:
    """Insert a user with either missing or current legal consent.

    Args:
        api_session: Async sessionmaker bound to the test engine.
        accepted: Whether to seed current accepted legal versions.

    Returns:
        Persisted user row.
    """
    async with api_session() as session:
        user = User(email=f"{uuid4()}@x.com", tz="UTC", status="active")
        if accepted:
            user.privacy_policy_version_accepted = CURRENT_PRIVACY_POLICY_VERSION
            user.terms_version_accepted = CURRENT_TERMS_VERSION
        session.add(user)
        await session.commit()
        return user


def _cookie_for(user: User) -> str:
    """Return a signed test session cookie for ``user``.

    Args:
        user: Authenticated user row.

    Returns:
        Signed cookie value accepted by :func:`current_user_id`.
    """
    return sign_cookie({"user_id": str(user.id)}, secret="test-key")


async def test_get_legal_consent_requires_acceptance_for_new_user(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """A new user reports version ``0`` and ``consent_required=true``."""
    user = await _seed_user(api_session)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/legal/consent",
            cookies={SESSION_COOKIE_NAME: _cookie_for(user)},
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "current_privacy_policy_version": CURRENT_PRIVACY_POLICY_VERSION,
        "current_terms_version": CURRENT_TERMS_VERSION,
        "accepted_privacy_policy_version": 0,
        "accepted_terms_version": 0,
        "consent_required": True,
        "accepted_at": None,
    }


async def test_post_legal_consent_accepts_current_versions(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """Posting current versions stores acceptance and returns an ungated status."""
    user = await _seed_user(api_session)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/legal/consent",
            cookies={SESSION_COOKIE_NAME: _cookie_for(user)},
            headers={"user-agent": "BriefedTest/1.0"},
            json={
                "privacy_policy_version": CURRENT_PRIVACY_POLICY_VERSION,
                "terms_version": CURRENT_TERMS_VERSION,
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted_privacy_policy_version"] == CURRENT_PRIVACY_POLICY_VERSION
    assert body["accepted_terms_version"] == CURRENT_TERMS_VERSION
    assert body["consent_required"] is False
    assert body["accepted_at"] is not None

    async with api_session() as session:
        persisted = await session.get(User, user.id)
    assert persisted is not None
    assert persisted.legal_accepted_user_agent == "BriefedTest/1.0"


async def test_get_legal_consent_after_acceptance_is_not_required(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """An already accepted user does not need to re-accept unchanged versions."""
    user = await _seed_user(api_session, accepted=True)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/legal/consent",
            cookies={SESSION_COOKIE_NAME: _cookie_for(user)},
        )
    assert response.status_code == 200, response.text
    assert response.json()["consent_required"] is False


async def test_post_legal_consent_rejects_version_mismatch(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """A stale client cannot accept non-current policy versions."""
    user = await _seed_user(api_session)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/legal/consent",
            cookies={SESSION_COOKIE_NAME: _cookie_for(user)},
            headers={"x-request-id": "test-consent-mismatch"},
            json={"privacy_policy_version": CURRENT_PRIVACY_POLICY_VERSION, "terms_version": 999},
        )
    assert response.status_code == 422, response.text
    assert response.json() == {
        "code": "consent_version_mismatch",
        "message": "Consent versions must match the current policies.",
        "details": {
            "current_privacy_policy_version": CURRENT_PRIVACY_POLICY_VERSION,
            "current_terms_version": CURRENT_TERMS_VERSION,
        },
        "requestId": "test-consent-mismatch",
    }


async def test_post_legal_consent_rejects_malformed_payload(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """Malformed consent payloads fail validation before persistence."""
    user = await _seed_user(api_session)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/legal/consent",
            cookies={SESSION_COOKIE_NAME: _cookie_for(user)},
            json={
                "privacy_policy_version": 0,
                "terms_version": CURRENT_TERMS_VERSION,
                "unexpected": True,
            },
        )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"]


async def test_get_legal_consent_missing_cookie_returns_401(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """The consent endpoint stays authenticated."""
    with TestClient(app) as client:
        response = client.get("/api/v1/legal/consent")
    assert response.status_code == 401, response.text


async def test_get_legal_consent_missing_user_returns_404(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """A valid session pointing at no user returns the project error envelope."""
    cookie = sign_cookie({"user_id": str(uuid4())}, secret="test-key")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/legal/consent",
            cookies={SESSION_COOKIE_NAME: cookie},
            headers={"x-request-id": "test-consent-404"},
        )
    assert response.status_code == 404, response.text
    assert response.json() == {
        "code": "user_not_found",
        "message": "User not found.",
        "details": {},
        "requestId": "test-consent-404",
    }
