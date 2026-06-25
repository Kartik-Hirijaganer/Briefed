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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.clock import utcnow
from app.core.errors import AuthError, ProviderError

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
"""Google OAuth authorize endpoint."""

TOKEN_URL = "https://oauth2.googleapis.com/token"  # nosec B105 - public OAuth endpoint URL
"""Google OAuth token-exchange endpoint."""

REVOKE_URL = "https://oauth2.googleapis.com/revoke"
"""Google OAuth revoke endpoint."""


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
"""Gmail scope used for message ingestion."""

GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
"""Gmail scope used only for explicit mark-read label removal."""

GMAIL_SCOPES: tuple[str, ...] = (
    GMAIL_READONLY_SCOPE,
    GMAIL_MODIFY_SCOPE,
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
)
"""Scopes requested by the 1.0.0 ingest + explicit mark-read pipeline."""

GMAIL_READONLY_SCOPES: tuple[str, ...] = GMAIL_SCOPES
"""Backward-compatible alias for callers that use the historical constant name."""

_GMAIL_MODIFY_SCOPE_SUFFIX = "/gmail.modify"
"""Suffix accepted when Google returns normalized Gmail modify scope strings."""


def has_gmail_modify_scope(scopes: tuple[str, ...]) -> bool:
    """Return whether granted scopes include Gmail modify.

    Args:
        scopes: Raw OAuth scope strings persisted from Google.

    Returns:
        True when ``gmail.modify`` was granted.
    """
    return any(
        scope == GMAIL_MODIFY_SCOPE or scope.endswith(_GMAIL_MODIFY_SCOPE_SUFFIX)
        for scope in scopes
    )


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


class OAuthErrorPayload(BaseModel):
    """OAuth error response returned by Google token endpoints.

    Attributes:
        error: Stable OAuth error code, such as ``invalid_grant``.
        error_description: Optional human-readable provider explanation.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    error: str = Field(description="Stable OAuth error code returned by Google.")
    error_description: str | None = Field(
        default=None,
        description="Optional provider explanation for the OAuth error.",
    )


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
    select_account: bool = False,
) -> str:
    """Build the Google consent-screen URL for the start-of-flow redirect.

    Args:
        client_id: Google OAuth client id from Infisical.
        redirect_uri: URL Google should redirect back to (must match the
            URI registered in the Cloud console).
        state: Opaque state token the caller stored in a signed cookie.
        code_challenge: PKCE challenge from :func:`generate_pkce_pair`.
        scopes: Requested scope strings.
        select_account: Whether Google should show the account chooser.

    Returns:
        A fully-qualified Google authorize URL.
    """
    prompt = "consent select_account" if select_account else "consent"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": prompt,
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
    body = _decode_json_response(response)
    _raise_for_oauth_error(
        response=response,
        body=body,
        auth_context="Google rejected token exchange",
        provider_context="Google token endpoint unavailable",
    )
    try:
        return OAuthTokenBundle.model_validate(body)
    except ValidationError as exc:
        raise ProviderError("Google token endpoint returned malformed token payload") from exc


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
    body = _decode_json_response(response)
    _raise_for_oauth_error(
        response=response,
        body=body,
        auth_context="refresh token rejected",
        provider_context="token endpoint unavailable",
    )
    try:
        return OAuthTokenBundle.model_validate(body)
    except ValidationError as exc:
        raise ProviderError("token endpoint returned malformed token payload") from exc


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


def _decode_json_response(response: httpx.Response) -> object:
    """Decode an HTTP JSON response body.

    Args:
        response: Raw provider response.

    Returns:
        Parsed JSON payload, or ``None`` when the body is empty or malformed.
    """
    try:
        return response.json()
    except ValueError:
        return None


def _raise_for_oauth_error(
    *,
    response: httpx.Response,
    body: object,
    auth_context: str,
    provider_context: str,
) -> None:
    """Raise typed errors for OAuth provider failure responses.

    Args:
        response: Raw provider response.
        body: Parsed JSON response body.
        auth_context: Prefix for user/action-related OAuth failures.
        provider_context: Prefix for upstream availability failures.

    Raises:
        AuthError: If Google returns an OAuth 4xx error.
        ProviderError: If Google returns a 5xx error.
    """
    if response.status_code >= 500:
        raise ProviderError(f"{provider_context}: {response.status_code}")
    if isinstance(body, dict) and "error" in body:
        error_payload = OAuthErrorPayload.model_validate(body)
        detail = error_payload.error
        if error_payload.error_description:
            detail = f"{detail}: {error_payload.error_description}"
        raise AuthError(f"{auth_context}: {detail}")
    if response.status_code >= 400:
        raise AuthError(f"{auth_context}: HTTP {response.status_code}")


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
