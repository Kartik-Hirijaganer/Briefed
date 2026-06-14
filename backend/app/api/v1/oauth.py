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

import re
import secrets
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode
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
from app.core.errors import AuthError, CryptoError, ProviderError
from app.core.security import EnvelopeCipher, token_context
from app.db.models import ConnectedAccount, OAuthToken, RubricRule, User
from app.db.session import get_sessionmaker
from app.services.classification.rubric import default_rubric_seed
from app.services.gmail.oauth import (
    OAuthTokenBundle,
    build_authorize_url,
    exchange_code,
    expires_at_from_bundle,
    generate_pkce_pair,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import KmsClient


router = APIRouter(prefix="/oauth/gmail", tags=["oauth"])

_LOGIN_PATH = "/login"
"""SPA route shown to unauthenticated users; OAuth denials bounce here."""

_RETURN_TO_PATTERN = re.compile(r"^/app(/[^/].*)?$")
"""Allowed post-OAuth UI paths."""

_OAUTH_STATE_COOKIE_MAX_AGE_SECONDS = 30 * 60
"""How long a user may spend in Google consent before callback validation."""


def sanitize_return_to(value: str | None) -> str:
    """Normalize an OAuth return path to the app route tree.

    Args:
        value: User-supplied return path from the OAuth start request or
            signed state cookie.

    Returns:
        ``value`` when it is an internal ``/app`` path, otherwise ``/app``.
    """
    if not value or "\\" in value:
        return "/app"
    if _RETURN_TO_PATTERN.fullmatch(value):
        return value
    return "/app"


def _compute_redirect_uri(request: Request, settings: Settings) -> str:
    """Build the canonical callback URL from the incoming request.

    Args:
        request: Current FastAPI request.
        settings: Cached app settings.

    Returns:
        Absolute URL, e.g. ``https://api.briefed.dev/api/v1/oauth/gmail/callback``.
    """
    callback_url = request.url_for("gmail_oauth_callback")
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}{callback_url.path}"

    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        scheme = (
            request.headers.get("x-forwarded-proto")
            or request.headers.get("cloudfront-forwarded-proto")
            or callback_url.scheme
        )
        return f"{scheme}://{forwarded_host}{callback_url.path}"

    return str(callback_url)


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
            absolute path under ``/app``, e.g. ``/app/settings/accounts``).
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
        "return_to": sanitize_return_to(return_to),
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
        redirect_uri=_compute_redirect_uri(request, settings),
        state=state,
        code_challenge=challenge,
    )
    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        cookie_value,
        max_age=_OAUTH_STATE_COOKIE_MAX_AGE_SECONDS,
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
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    oauth_state_cookie: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Handle the Google consent-screen redirect.

    Google redirects here with either ``code`` (success) or ``error`` (the
    user cancelled / denied consent — RFC 6749 §4.1.2.1). Both success
    parameters are optional so a denial never fails request validation with
    a raw 422; the error path bounces to the login page instead.

    Args:
        request: FastAPI request.
        code: Authorization code from Google, present on success.
        state: State parameter Google echoed back, present on success.
        error: OAuth error code (e.g. ``access_denied``) on user denial.
        oauth_state_cookie: Pre-authorize cookie set by :func:`start`.
        settings: Cached :class:`Settings`.

    Returns:
        A 302 redirect back to the UI (``return_to`` or ``/app``) on success,
        or to ``/login`` carrying an ``auth_error`` code on denial / a
        malformed callback.

    Raises:
        HTTPException: 400 on state mismatch / missing cookie; 503 when
            server OAuth configuration is missing.
    """
    # RFC 6749 §4.1.2.1: on cancel/deny Google sends ``error`` and no
    # ``code``. Surface it on the login page instead of 422-ing on the
    # missing required query parameter.
    if error:
        return _redirect_after_oauth_error(error)
    if not code or not state:
        return _redirect_after_oauth_error("invalid_request")

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

    bundle = await _exchange_callback_code(
        code=code,
        code_verifier=str(cookie["code_verifier"]),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=_compute_redirect_uri(request, settings),
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
        access_token_ct, refresh_token_ct = _encrypt_oauth_tokens(
            cipher=cipher,
            account_id=account.id,
            access_token=bundle.access_token,
            refresh_token=bundle.refresh_token,
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
                access_token_ct=access_token_ct,
                refresh_token_ct=refresh_token_ct,
                scope=bundle.scope.split(),
                expires_at=expires_at_from_bundle(bundle),
            )
            session.add(tokens)
        else:
            tokens.access_token_ct = access_token_ct
            tokens.refresh_token_ct = refresh_token_ct
            tokens.scope = bundle.scope.split()
            tokens.expires_at = expires_at_from_bundle(bundle)
        user.last_login_at = utcnow()
        await session.commit()
        user_id = user.id

    cookie_return_to = cookie.get("return_to")
    return_to = sanitize_return_to(cookie_return_to if isinstance(cookie_return_to, str) else None)
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


def _redirect_after_oauth_error(error: str) -> RedirectResponse:
    """Bounce a failed authorization response back to the login page.

    Google redirects to the callback with an ``error`` query parameter (and
    no ``code``) when the user cancels or denies consent (RFC 6749
    §4.1.2.1). Rather than failing request validation with a raw 422, send
    the browser to the SPA login page with a stable error code the UI maps
    to a friendly message.

    Args:
        error: Stable OAuth error code (e.g. ``access_denied``), or
            ``invalid_request`` when the callback was malformed.

    Returns:
        A 302 redirect to ``/login`` carrying the ``auth_error`` code; the
        stale pre-authorize cookie is cleared in passing.
    """
    query = urlencode({"auth_error": error})
    response = RedirectResponse(f"{_LOGIN_PATH}?{query}", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME)
    return response


async def _exchange_callback_code(
    *,
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> OAuthTokenBundle:
    """Exchange Google's callback code and map provider errors to HTTP errors.

    Args:
        code: Authorization code from Google's callback query.
        code_verifier: PKCE verifier from the signed OAuth-state cookie.
        client_id: Google OAuth client id.
        client_secret: Google OAuth client secret.
        redirect_uri: Callback URI used in the original authorize request.

    Returns:
        Token bundle returned by Google's token endpoint.

    Raises:
        HTTPException: 400 for invalid/reused codes and 503 for transient
            token endpoint failures.
    """
    try:
        return await exchange_code(
            code=code,
            code_verifier=code_verifier,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


def _encrypt_oauth_tokens(
    *,
    cipher: EnvelopeCipher,
    account_id: UUID,
    access_token: str,
    refresh_token: str,
) -> tuple[bytes, bytes]:
    """Encrypt access and refresh tokens for persistence.

    Args:
        cipher: Token-wrap envelope cipher.
        account_id: Connected-account id to bind into the KMS context.
        access_token: Short-lived Google access token.
        refresh_token: Long-lived Google refresh token.

    Returns:
        ``(access_token_ct, refresh_token_ct)`` ciphertext blobs.

    Raises:
        HTTPException: 503 when KMS/token wrapping is unavailable.
    """
    try:
        access_blob = cipher.encrypt(
            access_token.encode("utf-8"),
            token_context(account_id=str(account_id), purpose="access_token"),
        )
        refresh_blob = cipher.encrypt(
            refresh_token.encode("utf-8"),
            token_context(account_id=str(account_id), purpose="refresh_token"),
        )
    except CryptoError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="token encryption unavailable",
        ) from exc
    return access_blob.ciphertext, refresh_blob.ciphertext


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
    user = User(email=email, tz="America/New_York", status="active")
    session.add(user)
    await session.flush()
    for rule in _default_rubric_rules_for(user_id=user.id):
        session.add(rule)
    await session.flush()
    return user


def _default_rubric_rules_for(*, user_id: UUID) -> tuple[RubricRule, ...]:
    """Build the default rule rows for a newly-provisioned user.

    Args:
        user_id: New owner id.

    Returns:
        Rubric rule ORM rows ready to insert in the caller's transaction.
    """
    rows: list[RubricRule] = []
    for seed in default_rubric_seed():
        rows.append(
            RubricRule(
                user_id=user_id,
                name=cast(str, seed["name"]),
                priority=cast(int, seed["priority"]),
                match=cast(dict[str, object], seed["match"]),
                action=cast(dict[str, object], seed["action"]),
                version=1,
                active=True,
            ),
        )
    return tuple(rows)


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
