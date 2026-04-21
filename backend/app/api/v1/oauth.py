"""OAuth start + callback endpoints for Gmail connect.

Flow (plan §14 Phase 1 — "OAuth start/callback routers"):

* ``GET /api/v1/oauth/gmail/start`` — redirects the user to Google's
  consent screen, stores a signed pre-authorize cookie with the PKCE
  verifier + random state.
* ``GET /api/v1/oauth/gmail/callback`` — verifies the cookie, exchanges
  ``code`` for tokens, encrypts them with KMS CMK, persists
  :class:`ConnectedAccount` + :class:`OAuthToken`, and sets the signed
  session cookie before redirecting back to the UI.

Secrets access: the OAuth client id + secret come from SSM via
:class:`app.core.config.Settings`. The KMS CMK alias comes from
``settings.token_wrap_key_alias`` injected by Terraform.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, cast
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.session import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    sign_cookie,
    verify_cookie,
)
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.core.errors import AuthError
from app.core.security import EnvelopeCipher, token_context
from app.db.models import ConnectedAccount, OAuthToken, User
from app.db.session import get_sessionmaker
from app.services.gmail.oauth import (
    build_authorize_url,
    exchange_code,
    expires_at_from_bundle,
    generate_pkce_pair,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import KmsClient


router = APIRouter(prefix="/oauth/gmail", tags=["oauth"])


def _compute_redirect_uri(request: Request) -> str:
    """Build the canonical callback URL from the incoming request.

    Args:
        request: Current FastAPI request.

    Returns:
        Absolute URL, e.g. ``https://api.briefed.dev/api/v1/oauth/gmail/callback``.
    """
    return str(request.url_for("gmail_oauth_callback"))


def _require_session_key(settings: Settings) -> str:
    """Return a non-empty ``session_signing_key`` or raise 503.

    Args:
        settings: Cached :class:`Settings`.

    Returns:
        The session signing key.

    Raises:
        HTTPException: 503 when the key is not configured.
    """
    if not settings.session_signing_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="session signing key not configured",
        )
    return settings.session_signing_key


def _require_oauth_credentials(settings: Settings) -> tuple[str, str]:
    """Return ``(client_id, client_secret)`` or raise 503.

    Args:
        settings: Cached :class:`Settings`.

    Returns:
        Google OAuth client id + secret.

    Raises:
        HTTPException: 503 when credentials are not configured.
    """
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    if not client_id or not client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth credentials not configured",
        )
    return client_id, client_secret


@router.get(
    "/start",
    name="gmail_oauth_start",
    summary="Start Google OAuth authorization-code flow",
)
async def start(
    request: Request,
    return_to: str | None = Query(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Generate PKCE + state, set the cookie, redirect to Google.

    Args:
        request: FastAPI request (used to compute the callback URL).
        return_to: Optional post-callback UI path (must be an internal
            absolute path, e.g. ``/settings/accounts``).
        session_cookie: Existing signed session, when the caller is
            connecting another mailbox to the same user.
        settings: Cached :class:`Settings`.

    Returns:
        A 302 redirect to Google's consent screen.
    """
    client_id, _client_secret = _require_oauth_credentials(settings)
    signing_key = _require_session_key(settings)

    state = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce_pair()
    cookie_payload = {
        "state": state,
        "code_verifier": verifier,
        "return_to": return_to if return_to and return_to.startswith("/") else None,
    }
    if session_cookie:
        try:
            existing_session = verify_cookie(session_cookie, secret=signing_key)
        except AuthError:
            existing_session = {}
        existing_user_id = existing_session.get("user_id")
        if isinstance(existing_user_id, str):
            cookie_payload["user_id"] = existing_user_id
    cookie_value = sign_cookie(cookie_payload, secret=signing_key)

    url = build_authorize_url(
        client_id=client_id,
        redirect_uri=_compute_redirect_uri(request),
        state=state,
        code_challenge=challenge,
    )
    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        cookie_value,
        max_age=600,
        httponly=True,
        secure=settings.runtime != "local",
        samesite="lax",
    )
    return response


@router.get(
    "/callback",
    name="gmail_oauth_callback",
    summary="Google OAuth callback — exchange code, persist account",
)
async def callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    oauth_state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Handle the Google consent-screen redirect.

    Args:
        request: FastAPI request.
        code: Authorization code from Google.
        state: State parameter Google echoed back.
        oauth_state_cookie: Pre-authorize cookie set by :func:`start`.
        settings: Cached :class:`Settings`.

    Returns:
        A 302 redirect back to the UI (``return_to`` or ``/``).

    Raises:
        HTTPException: 400 when the state mismatch / cookie missing.
    """
    client_id, client_secret = _require_oauth_credentials(settings)
    signing_key = _require_session_key(settings)
    if not oauth_state_cookie:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="missing state cookie")
    try:
        cookie = verify_cookie(oauth_state_cookie, secret=signing_key)
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if cookie.get("state") != state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="state mismatch")

    bundle = await exchange_code(
        code=code,
        code_verifier=str(cookie["code_verifier"]),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=_compute_redirect_uri(request),
    )
    if not bundle.refresh_token:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Google did not return a refresh_token; re-consent required",
        )

    identity = _extract_identity_from_id_token(bundle.id_token)
    if identity is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Google id_token did not include an email claim",
        )
    email, gmail_account_id = identity
    cipher = _build_token_cipher(settings)

    async with get_sessionmaker()() as session:
        requested_user_id = _uuid_from_cookie(cookie.get("user_id"))
        if requested_user_id is not None:
            user = await session.get(User, requested_user_id)
            if user is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="session user not found")
        else:
            user = await _get_or_create_user(session, email=email)
        account = await _upsert_connected_account(
            session,
            user_id=user.id,
            email=email,
            gmail_account_id=gmail_account_id,
        )
        access_blob = cipher.encrypt(
            bundle.access_token.encode("utf-8"),
            token_context(account_id=str(account.id), purpose="access_token"),
        )
        refresh_blob = cipher.encrypt(
            bundle.refresh_token.encode("utf-8"),
            token_context(account_id=str(account.id), purpose="refresh_token"),
        )
        tokens = (
            (
                await session.execute(
                    select(OAuthToken).where(OAuthToken.account_id == account.id),
                )
            )
            .scalars()
            .first()
        )
        if tokens is None:
            tokens = OAuthToken(
                account_id=account.id,
                access_token_ct=access_blob.ciphertext,
                refresh_token_ct=refresh_blob.ciphertext,
                scope=bundle.scope.split(),
                expires_at=expires_at_from_bundle(bundle),
            )
            session.add(tokens)
        else:
            tokens.access_token_ct = access_blob.ciphertext
            tokens.refresh_token_ct = refresh_blob.ciphertext
            tokens.scope = bundle.scope.split()
            tokens.expires_at = expires_at_from_bundle(bundle)
        user.last_login_at = utcnow()
        await session.commit()
        user_id = user.id

    return_to = cookie.get("return_to") or "/"
    response = RedirectResponse(str(return_to), status_code=status.HTTP_302_FOUND)
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        sign_cookie({"user_id": str(user_id)}, secret=signing_key),
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        secure=settings.runtime != "local",
        samesite="lax",
    )
    return response


def _build_token_cipher(settings: Settings) -> EnvelopeCipher:
    """Construct the :class:`EnvelopeCipher` for OAuth wrap/unwrap.

    Args:
        settings: Cached :class:`Settings`.

    Returns:
        A ready-to-use cipher.

    Raises:
        HTTPException: 503 when the KMS alias is not configured.
    """
    alias = settings.token_wrap_key_alias
    if not alias:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="KMS token-wrap alias not configured",
        )
    import boto3  # type: ignore[import-untyped]

    return EnvelopeCipher(key_id=alias, client=cast("KmsClient", boto3.client("kms")))


def _extract_identity_from_id_token(id_token: str | None) -> tuple[str, str | None] | None:
    """Decode stable identity claims from a Google id_token.

    Signature verification is deferred to a later phase; the token was
    received directly from Google's HTTPS token endpoint. We still
    require an ``email`` claim and persist ``sub`` when present so account
    swaps can be detected.

    Args:
        id_token: The raw id_token string (may be ``None``).

    Returns:
        ``(email, sub)`` or ``None`` when absent / malformed.
    """
    if not id_token:
        return None
    segments = id_token.split(".")
    if len(segments) != 3:
        return None
    import base64
    import json

    body = segments[1]
    padding = 4 - (len(body) % 4)
    if padding != 4:
        body = body + ("=" * padding)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    email = payload.get("email")
    if not isinstance(email, str) or not email:
        return None
    sub = payload.get("sub")
    return email, str(sub) if isinstance(sub, str) and sub else None


def _uuid_from_cookie(value: object) -> UUID | None:
    """Return a UUID from a signed cookie payload value, ignoring blanks."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid session user id") from exc


async def _get_or_create_user(
    session: AsyncSession,
    *,
    email: str,
) -> User:
    """Return an existing user or create one.

    Args:
        session: Open async session.
        email: Owner email from the id_token.

    Returns:
        The loaded / created :class:`User`.
    """
    existing = (
        (
            await session.execute(
                select(User).where(User.email == email),
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    user = User(email=email, tz="UTC", status="active")
    session.add(user)
    await session.flush()
    return user


async def _upsert_connected_account(
    session: AsyncSession,
    *,
    user_id: UUID,
    email: str,
    gmail_account_id: str | None,
) -> ConnectedAccount:
    """Return an existing account by (user_id, email) or create one.

    Args:
        session: Open async session.
        user_id: Owning user id.
        email: Mailbox email.
        gmail_account_id: Google ``sub`` claim, when present.

    Returns:
        The loaded / created :class:`ConnectedAccount`.
    """
    existing = (
        (
            await session.execute(
                select(ConnectedAccount).where(
                    ConnectedAccount.user_id == user_id,
                    ConnectedAccount.email == email,
                ),
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        existing.status = "active"
        existing.gmail_account_id = gmail_account_id
        return existing
    account = ConnectedAccount(
        user_id=user_id,
        provider="gmail",
        email=email,
        gmail_account_id=gmail_account_id,
        status="active",
    )
    session.add(account)
    await session.flush()
    return account
