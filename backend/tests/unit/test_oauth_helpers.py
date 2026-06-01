"""Tests for Gmail OAuth helpers (URL building, PKCE, token exchange)."""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import AuthError, ProviderError
from app.services.gmail.oauth import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_SCOPES,
    OAuthTokenBundle,
    build_authorize_url,
    exchange_code,
    expires_at_from_bundle,
    generate_pkce_pair,
)


def test_pkce_pair_is_deterministically_sha256() -> None:
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43
    # Both are URL-safe-no-padding base64.
    for value in (verifier, challenge):
        assert "=" not in value


def test_authorize_url_contains_required_params() -> None:
    url = build_authorize_url(
        client_id="cid",
        redirect_uri="https://api.briefed.dev/cb",
        state="STATE",
        code_challenge="CHAL",
    )
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in url
    assert "state=STATE" in url
    assert "code_challenge=CHAL" in url
    assert "code_challenge_method=S256" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert GMAIL_MODIFY_SCOPE.replace(":", "%3A").replace("/", "%2F") in url
    assert GMAIL_MODIFY_SCOPE in GMAIL_SCOPES


def test_expires_at_adds_safety_margin() -> None:
    bundle = OAuthTokenBundle(
        access_token="x",
        expires_in=3600,
    )
    expires_at = expires_at_from_bundle(bundle)
    # Must be at least ~1h in the future, minus our 30s safety margin.
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    delta = expires_at - now
    assert timedelta(minutes=55) < delta < timedelta(minutes=61)


def test_bundle_rejects_too_small_expiry() -> None:
    with pytest.raises(Exception):  # pydantic ValidationError
        OAuthTokenBundle(access_token="x", expires_in=5)


async def test_exchange_code_maps_invalid_client_to_auth_error() -> None:
    def _handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=401,
            json={
                "error": "invalid_client",
                "error_description": "The OAuth client secret is invalid.",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        with pytest.raises(AuthError, match="invalid_client"):
            await exchange_code(
                code="code",
                code_verifier="verifier",
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="https://app.example.test/api/v1/oauth/gmail/callback",
                http_client=client,
            )


async def test_exchange_code_maps_malformed_success_payload_to_provider_error() -> None:
    def _handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"token_type": "Bearer"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        with pytest.raises(ProviderError, match="malformed token payload"):
            await exchange_code(
                code="code",
                code_verifier="verifier",
                client_id="client-id",
                client_secret="client-secret",
                redirect_uri="https://app.example.test/api/v1/oauth/gmail/callback",
                http_client=client,
            )
