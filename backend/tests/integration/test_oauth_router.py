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

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import db_session
from app.api.session import OAUTH_STATE_COOKIE_NAME, sign_cookie
from app.api.v1.oauth import _build_token_cipher
from app.core.config import Settings, get_settings
from app.core.security import EncryptionContext, EnvelopeCipher
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
        # Mint a fake id_token with the email claim Google would send.
        header = _b64({"alg": "none"})
        body = _b64({"email": "user@example.com"})
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
        return Settings(
            env="test",
            runtime="local",
            log_level="info",
            session_signing_key="test-key",
            google_oauth_client_id="cid",
            google_oauth_client_secret="csec",
            token_wrap_key_alias="alias/test",
        )

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
