"""E2E: OAuth start → callback sets cookie → /api/accounts lists the new account.

Drives the full Phase 1 auth loop with fakes for Google's /token endpoint
and KMS. Plan §14 Phase 1 — "e2e — OAuth start → callback sets cookie →
/api/accounts lists the new account".
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import db_session
from app.api.session import OAUTH_STATE_COOKIE_NAME, SESSION_COOKIE_NAME, sign_cookie, verify_cookie
from app.api.v1.oauth import _build_token_cipher, _get_or_create_user
from app.core.config import Settings, get_settings
from app.core.errors import AuthError
from app.core.security import EncryptionContext, EnvelopeCipher
from app.db.models import ConnectedAccount, RubricRule, User
from app.main import app
from app.services.gmail import oauth as oauth_module


class _FakeKms:
    """Context-preserving stub — not cryptographically secure, tests only."""

    def encrypt(
        self,
        *,
        KeyId: str,
        Plaintext: bytes,
        EncryptionContext: dict[str, str],
    ) -> dict[str, Any]:
        return {"CiphertextBlob": b"K:" + Plaintext}

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,
        EncryptionContext: dict[str, str],
        KeyId: str | None = None,
    ) -> dict[str, Any]:
        assert CiphertextBlob.startswith(b"K:")
        return {"Plaintext": CiphertextBlob[2:]}


class _FailingKms:
    """KMS stub that fails encrypt calls."""

    def encrypt(
        self,
        *,
        KeyId: str,
        Plaintext: bytes,
        EncryptionContext: dict[str, str],
    ) -> dict[str, Any]:
        raise RuntimeError("missing key")

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,
        EncryptionContext: dict[str, str],
        KeyId: str | None = None,
    ) -> dict[str, Any]:
        raise AssertionError("decrypt should not be called")


class _FakeTokenExchange:
    """Replaces :func:`app.services.gmail.oauth.exchange_code`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        *,
        code: str,
        code_verifier: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> oauth_module.OAuthTokenBundle:
        self.calls.append(
            {
                "code": code,
                "verifier": code_verifier,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            }
        )
        email_by_code = {
            "second": "second@example.com",
            "xyz": "user@example.com",
        }
        email = email_by_code.get(code, "user@example.com")
        # Mint a fake id_token with the email claim Google would send.
        header = _b64({"alg": "none"})
        body = _b64({"email": email, "sub": f"sub-{email}"})
        id_token = f"{header}.{body}.sig"
        return oauth_module.OAuthTokenBundle(
            access_token="access-xyz",
            refresh_token="refresh-abc",
            expires_in=3600,
            scope="https://www.googleapis.com/auth/gmail.readonly",
            id_token=id_token,
        )


def _b64(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _test_settings(*, public_base_url: str | None = None) -> Settings:
    """Build the test settings used by OAuth route tests.

    Args:
        public_base_url: Optional public app origin for callback generation.

    Returns:
        Settings with stable fake credentials and signing keys.
    """
    return Settings(
        env="test",
        runtime="local",
        log_level="info",
        session_signing_key="test-key",
        google_oauth_client_id="cid",
        google_oauth_client_secret="csec",
        token_wrap_key_alias="alias/test",
        public_base_url=public_base_url,
    )


def _redirect_uri_from_location(location: str) -> str:
    """Extract the Google OAuth ``redirect_uri`` query parameter.

    Args:
        location: Google authorization URL from the OAuth start response.

    Returns:
        Decoded ``redirect_uri`` value.
    """
    values = parse_qs(urlparse(location).query)["redirect_uri"]
    return values[0]


def _query_value_from_location(location: str, key: str) -> str:
    """Extract a query value from a redirect URL.

    Args:
        location: Redirect target URL.
        key: Query key to extract.

    Returns:
        First decoded query value.
    """
    return parse_qs(urlparse(location).query)[key][0]


@pytest_asyncio.fixture()
async def wired_app(
    test_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[TestClient]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def _settings() -> Settings:
        return _test_settings()

    # Replace the KMS builder so the router never touches boto3.
    monkeypatch.setattr(
        "app.api.v1.oauth._build_token_cipher",
        lambda settings: EnvelopeCipher(key_id="alias/test", client=_FakeKms()),
    )
    # Replace the /token call with our fake.
    fake_exchange = _FakeTokenExchange()
    monkeypatch.setattr("app.api.v1.oauth.exchange_code", fake_exchange)
    # Fake the session factory used inside the oauth router.
    monkeypatch.setattr("app.api.v1.oauth.get_sessionmaker", lambda: factory)

    app.dependency_overrides[db_session] = _override_session
    app.dependency_overrides[get_settings] = _settings
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_oauth_start_redirects_to_google_and_sets_state_cookie(
    wired_app: TestClient,
) -> None:
    response = wired_app.get(
        "/api/v1/oauth/gmail/start",
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    assert response.headers["location"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?",
    )
    assert OAUTH_STATE_COOKIE_NAME in response.cookies


def test_oauth_start_uses_public_base_url_for_callback(wired_app: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: _test_settings(
        public_base_url="https://app.example.test",
    )
    response = wired_app.get(
        "/api/v1/oauth/gmail/start",
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert _redirect_uri_from_location(response.headers["location"]) == (
        "https://app.example.test/api/v1/oauth/gmail/callback"
    )


def test_oauth_start_uses_forwarded_host_for_callback(wired_app: TestClient) -> None:
    response = wired_app.get(
        "/api/v1/oauth/gmail/start",
        headers={"x-forwarded-host": "app.example.test", "x-forwarded-proto": "https"},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert _redirect_uri_from_location(response.headers["location"]) == (
        "https://app.example.test/api/v1/oauth/gmail/callback"
    )


def test_oauth_callback_persists_account_and_sets_session_cookie(
    wired_app: TestClient,
) -> None:
    # Seed a signed state cookie manually so we can deterministically
    # supply code + state.
    cookie_payload = {
        "state": "STATE-123",
        "code_verifier": "V" * 50,
        "return_to": "/settings/accounts",
    }
    cookie_value = sign_cookie(cookie_payload, secret="test-key")
    wired_app.cookies.set(OAUTH_STATE_COOKIE_NAME, cookie_value)

    response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"code": "xyz", "state": "STATE-123"},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    assert response.headers["location"] == "/settings/accounts"
    # The session cookie is now set; /accounts should return our new row.
    list_response = wired_app.get("/api/v1/accounts")
    assert list_response.status_code == 200, list_response.text
    payload = list_response.json()
    assert len(payload["accounts"]) == 1
    assert payload["accounts"][0]["email"] == "user@example.com"


async def test_link_mode_adds_second_account_to_existing_user(
    wired_app: TestClient,
    test_engine: AsyncEngine,
) -> None:
    """An authenticated Add Gmail flow attaches the new mailbox to the same user."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = User(email="owner@example.com", tz="America/New_York", status="active")
        session.add(user)
        await session.flush()
        session.add(
            ConnectedAccount(
                user_id=user.id,
                provider="gmail",
                email="first@example.com",
                gmail_account_id="sub-first@example.com",
                status="active",
            ),
        )
        await session.commit()
        user_id = user.id

    wired_app.cookies.set(
        SESSION_COOKIE_NAME,
        sign_cookie({"user_id": str(user_id)}, secret="test-key"),
    )

    start_response = wired_app.get(
        "/api/v1/oauth/gmail/start",
        params={"link": "true", "return_to": "/app/settings/accounts"},
        follow_redirects=False,
    )

    assert start_response.status_code in (302, 307), start_response.text
    location = start_response.headers["location"]
    assert _query_value_from_location(location, "prompt") == "consent select_account"
    state = _query_value_from_location(location, "state")
    state_cookie = wired_app.cookies.get(OAUTH_STATE_COOKIE_NAME)
    assert state_cookie is not None
    state_payload = verify_cookie(state_cookie, secret="test-key")
    assert state_payload["user_id"] == str(user_id)
    assert state_payload["link"] is True

    callback_response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"code": "second", "state": state},
        follow_redirects=False,
    )

    assert callback_response.status_code == 302, callback_response.text
    assert callback_response.headers["location"] == "/app/settings/accounts"
    list_response = wired_app.get("/api/v1/accounts")
    assert list_response.status_code == 200, list_response.text
    emails = [row["email"] for row in list_response.json()["accounts"]]
    assert emails == ["first@example.com", "second@example.com"]


def test_link_mode_requires_existing_session(wired_app: TestClient) -> None:
    """Add Gmail should not silently create a new user when the session is gone."""
    response = wired_app.get(
        "/api/v1/oauth/gmail/start",
        params={"link": "true", "return_to": "/app/settings/accounts"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/login?next=%2Fapp%2Fsettings%2Faccounts"


async def test_non_link_login_ignores_existing_session_cookie(
    wired_app: TestClient,
    test_engine: AsyncEngine,
) -> None:
    """Normal login should not link a mailbox just because a session cookie exists."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = User(email="owner@example.com", tz="America/New_York", status="active")
        session.add(user)
        await session.flush()
        user_id = user.id
        await session.commit()

    wired_app.cookies.set(
        SESSION_COOKIE_NAME,
        sign_cookie({"user_id": str(user_id)}, secret="test-key"),
    )

    start_response = wired_app.get(
        "/api/v1/oauth/gmail/start",
        params={"return_to": "/app"},
        follow_redirects=False,
    )

    assert start_response.status_code in (302, 307), start_response.text
    state = _query_value_from_location(start_response.headers["location"], "state")
    state_cookie = wired_app.cookies.get(OAUTH_STATE_COOKIE_NAME)
    assert state_cookie is not None
    state_payload = verify_cookie(state_cookie, secret="test-key")
    assert "user_id" not in state_payload
    assert state_payload["link"] is False

    callback_response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"code": "xyz", "state": state},
        follow_redirects=False,
    )

    assert callback_response.status_code == 302, callback_response.text
    async with factory() as session:
        owner_accounts = (
            (
                await session.execute(
                    select(ConnectedAccount).where(ConnectedAccount.user_id == user_id),
                )
            )
            .scalars()
            .all()
        )
        login_user = (
            (await session.execute(select(User).where(User.email == "user@example.com")))
            .scalars()
            .one()
        )
        login_accounts = (
            (
                await session.execute(
                    select(ConnectedAccount).where(ConnectedAccount.user_id == login_user.id),
                )
            )
            .scalars()
            .all()
        )

    assert owner_accounts == []
    assert [account.email for account in login_accounts] == ["user@example.com"]


async def test_get_or_create_user_seeds_default_rubric_rules(
    test_engine: AsyncEngine,
) -> None:
    """First-time OAuth user provisioning inserts the default rubric rows."""
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = await _get_or_create_user(session, email="seeded@example.com")
        rows = (
            (
                await session.execute(
                    select(RubricRule)
                    .where(RubricRule.user_id == user.id)
                    .order_by(RubricRule.priority.desc()),
                )
            )
            .scalars()
            .all()
        )
        assert [row.name for row in rows] == [
            "Gmail important",
            "Security alerts",
            "Receipts and invoices",
            "Newsletters",
        ]

        same_user = await _get_or_create_user(session, email="seeded@example.com")
        repeat_rows = (
            (
                await session.execute(
                    select(RubricRule).where(RubricRule.user_id == user.id),
                )
            )
            .scalars()
            .all()
        )

    assert same_user.id == user.id
    assert len(repeat_rows) == len(rows)


def test_oauth_callback_redirects_to_login_on_access_denied(wired_app: TestClient) -> None:
    """User-denied consent (Google ``error``, no ``code``) bounces to /login, not a 422."""
    response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"error": "access_denied", "state": "STATE-123"},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    assert response.headers["location"] == "/login?auth_error=access_denied"


def test_oauth_callback_redirects_to_login_on_missing_code(wired_app: TestClient) -> None:
    """A callback with neither ``code`` nor ``error`` is malformed → /login, not a 422."""
    response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"state": "STATE-123"},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    assert response.headers["location"] == "/login?auth_error=invalid_request"


def test_oauth_callback_rejects_state_mismatch(wired_app: TestClient) -> None:
    cookie_value = sign_cookie(
        {"state": "A", "code_verifier": "V" * 50, "return_to": None},
        secret="test-key",
    )
    wired_app.cookies.set(OAUTH_STATE_COOKIE_NAME, cookie_value)
    response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"code": "c", "state": "B"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_oauth_callback_rejects_missing_cookie(wired_app: TestClient) -> None:
    response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"code": "c", "state": "S"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_oauth_callback_maps_token_exchange_auth_error(
    wired_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid / reused Google codes return 400 instead of a raw 500."""

    async def _reject_exchange(**_: object) -> oauth_module.OAuthTokenBundle:
        raise AuthError("Google rejected token exchange: invalid_grant")

    monkeypatch.setattr("app.api.v1.oauth.exchange_code", _reject_exchange)
    cookie_value = sign_cookie(
        {"state": "STATE-123", "code_verifier": "V" * 50, "return_to": None},
        secret="test-key",
    )
    wired_app.cookies.set(OAUTH_STATE_COOKIE_NAME, cookie_value)

    response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"code": "used-code", "state": "STATE-123"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "invalid_grant" in response.text


def test_oauth_callback_maps_token_encryption_error(
    wired_app: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local KMS / alias failures return 503 instead of a raw 500."""
    monkeypatch.setattr(
        "app.api.v1.oauth._build_token_cipher",
        lambda settings: EnvelopeCipher(key_id="alias/test", client=_FailingKms()),
    )
    cookie_value = sign_cookie(
        {"state": "STATE-123", "code_verifier": "V" * 50, "return_to": None},
        secret="test-key",
    )
    wired_app.cookies.set(OAUTH_STATE_COOKIE_NAME, cookie_value)

    response = wired_app.get(
        "/api/v1/oauth/gmail/callback",
        params={"code": "xyz", "state": "STATE-123"},
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "token encryption unavailable"


def test_build_token_cipher_rejects_missing_alias() -> None:
    from fastapi import HTTPException

    settings = Settings(env="test", runtime="local", log_level="info")
    with pytest.raises(HTTPException) as exc:
        _build_token_cipher(settings)
    assert exc.value.status_code == 503


def test_encryption_context_helper() -> None:
    # Kept next to the OAuth tests to validate the boundary object.
    ctx = EncryptionContext(fields={"x": "y"})
    assert ctx.as_kms_dict() == {"x": "y"}
