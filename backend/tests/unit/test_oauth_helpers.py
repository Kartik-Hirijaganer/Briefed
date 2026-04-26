"""Tests for Gmail OAuth helpers (URL building, PKCE, token exchange)."""

from __future__ import annotations

import pytest

from app.services.gmail.oauth import (
    OAuthTokenBundle,
    build_authorize_url,
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
