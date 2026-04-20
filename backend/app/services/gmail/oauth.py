"""Gmail OAuth 2.0 authorization-code flow helpers (plan §14 Phase 1).

The flow:

1. ``/api/v1/oauth/gmail/start`` generates a cryptographically random
   ``state`` + ``code_verifier``, stores them in a signed session
   cookie, and redirects the user to Google's authorize URL.
2. Google redirects back to ``/api/v1/oauth/gmail/callback`` with
   ``code`` + ``state``. The router validates ``state`` against the
   cookie, exchanges ``code`` for tokens, then persists them
   envelope-encrypted via :class:`app.core.security.EnvelopeCipher`.

This module owns the pure URL-building / exchange logic; it performs no
DB writes and no cookie management — the router composes those pieces.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.core.clock import utcnow
from app.core.errors import AuthError, ProviderError

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
"""Google OAuth authorize endpoint."""

TOKEN_URL = "https://oauth2.googleapis.com/token"
"""Google OAuth token-exchange endpoint."""

REVOKE_URL = "https://oauth2.googleapis.com/revoke"
"""Google OAuth revoke endpoint."""


GMAIL_READONLY_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
)
"""Scopes requested by the 1.0.0 ingest pipeline."""


class OAuthStartPayload(BaseModel):
    """State attached to the pre-authorize cookie.

    Attributes:
        state: Random opaque token round-tripped through Google.
        code_verifier: PKCE code-verifier (RFC-7636).
        return_to: Optional post-callback redirect target.
        user_id: Optional pre-existing user id the new account attaches to.
    """

    model_config = ConfigDict(frozen=True)

    state: str
    code_verifier: str
    return_to: str | None = Field(default=None)
    user_id: str | None = Field(default=None)


class OAuthTokenBundle(BaseModel):
    """Tokens returned by ``/token`` exchange or refresh.

    Attributes:
        access_token: Short-lived bearer token.
        refresh_token: Long-lived token (absent on subsequent refreshes).
        expires_in: Seconds until ``access_token`` expires.
        scope: Space-separated granted scopes.
        id_token: Optional ID token (present when ``openid`` was granted).
        token_type: Always ``"Bearer"`` in practice.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    access_token: str
    refresh_token: str | None = Field(default=None)
    expires_in: int = Field(default=3600, ge=60)
    scope: str = Field(default="")
    id_token: str | None = Field(default=None)
    token_type: str = Field(default="Bearer")


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE ``(verifier, challenge)`` pair (RFC-7636).

    Returns:
        A ``(code_verifier, code_challenge)`` tuple suitable for the
        Google authorize request. Both strings are URL-safe base64 with
        padding stripped.
    """
    verifier = secrets.token_urlsafe(64)
    challenge_bytes = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(challenge_bytes).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: tuple[str, ...] = GMAIL_READONLY_SCOPES,
) -> str:
    """Build the Google consent-screen URL for the start-of-flow redirect.

    Args:
        client_id: Google OAuth client id (from SSM).
        redirect_uri: URL Google should redirect back to (must match the
            URI registered in the Cloud console).
        state: Opaque state token the caller stored in a signed cookie.
        code_challenge: PKCE challenge from :func:`generate_pkce_pair`.
        scopes: Requested scope strings.

    Returns:
        A fully-qualified Google authorize URL.
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(
    *,
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http_client: httpx.AsyncClient | None = None,
) -> OAuthTokenBundle:
    """Exchange an authorization code for an access+refresh token pair.

    Args:
        code: The ``code`` query parameter returned by Google.
        code_verifier: The PKCE verifier stored in the pre-authorize cookie.
        client_id: Google OAuth client id.
        client_secret: Google OAuth client secret.
        redirect_uri: The same redirect URI used at authorize time.
        http_client: Optional pre-built :class:`httpx.AsyncClient`;
            mainly for tests.

    Returns:
        An :class:`OAuthTokenBundle` whose ``refresh_token`` is guaranteed
        non-``None`` on first consent.

    Raises:
        AuthError: If Google rejects the code / verifier.
        ProviderError: If Google returns a 5xx / network error.
    """
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    response = await _post_form(TOKEN_URL, payload, http_client)
    if response.status_code == 400:
        raise AuthError(f"Google rejected token exchange: {response.text}")
    if response.status_code >= 500:
        raise ProviderError(f"Google token endpoint unavailable: {response.status_code}")
    return OAuthTokenBundle.model_validate(response.json())


async def refresh_access_token(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    http_client: httpx.AsyncClient | None = None,
) -> OAuthTokenBundle:
    """Mint a fresh access token from a stored refresh token.

    Args:
        refresh_token: Previously-persisted refresh token (already decrypted).
        client_id: Google OAuth client id.
        client_secret: Google OAuth client secret.
        http_client: Optional pre-built client; mainly for tests.

    Returns:
        A new :class:`OAuthTokenBundle`. ``refresh_token`` may be ``None``
        (Google does not re-issue on every refresh); callers persist the
        old refresh token in that case.

    Raises:
        AuthError: If Google marked the refresh token invalid.
        ProviderError: On transient upstream failure.
    """
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    response = await _post_form(TOKEN_URL, payload, http_client)
    if response.status_code == 400:
        raise AuthError(f"refresh token rejected: {response.text}")
    if response.status_code >= 500:
        raise ProviderError(f"token endpoint unavailable: {response.status_code}")
    return OAuthTokenBundle.model_validate(response.json())


async def revoke_token(
    *,
    token: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Revoke a Google OAuth token; idempotent on already-revoked tokens.

    Args:
        token: The access or refresh token to revoke.
        http_client: Optional pre-built client for tests.
    """
    await _post_form(REVOKE_URL, {"token": token}, http_client)


async def _post_form(
    url: str,
    data: dict[str, Any],
    http_client: httpx.AsyncClient | None,
) -> httpx.Response:
    """POST a ``application/x-www-form-urlencoded`` body and return the response.

    Args:
        url: Target URL.
        data: Form data to send.
        http_client: Optional pre-built client; a short-lived one is
            constructed when ``None``.

    Returns:
        The raw :class:`httpx.Response`.
    """
    if http_client is None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.post(url, data=data)
    return await http_client.post(url, data=data)


def expires_at_from_bundle(bundle: OAuthTokenBundle) -> datetime:
    """Compute the absolute expiry :class:`datetime` for an access token.

    Args:
        bundle: Bundle returned by :func:`exchange_code` or
            :func:`refresh_access_token`.

    Returns:
        A UTC :class:`datetime` a few seconds before Google's declared
        expiry — callers treat it as the token's expiry instant.
    """
    # 30-second safety margin so a token about to expire is refreshed
    # before the next Gmail call rather than after a 401.
    return utcnow() + timedelta(seconds=max(60, bundle.expires_in - 30))
