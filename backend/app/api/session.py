"""Signed-cookie session management (plan §10 "Auth flow").

Release 1.0.0 ships single-user self-host, so authentication is a
signed cookie containing the owner's ``user_id``. The cookie is signed
with ``settings.session_signing_key`` using HMAC-SHA-256; this module
owns the sign/verify + pre-authorize-state envelope used by the OAuth
flow.

Later phases add TOTP MFA (§20.1) on top of the same cookie — this
module's API does not change.
"""

from __future__ import annotations

import base64
import hmac
import json
from hashlib import sha256
from typing import Any

from app.core.errors import AuthError

_SESSION_COOKIE = "briefed_session"
"""Name of the signed session cookie."""

_OAUTH_STATE_COOKIE = "briefed_oauth_state"
"""Name of the pre-authorize state cookie."""


def _b64url(raw: bytes) -> str:
    """Base64-URL-encode ``raw`` with no padding.

    Args:
        raw: Input bytes.

    Returns:
        ASCII text suitable for a cookie value.
    """
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """Inverse of :func:`_b64url`.

    Args:
        data: Base64-URL-encoded string.

    Returns:
        The decoded raw bytes.
    """
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data = data + ("=" * padding)
    return base64.urlsafe_b64decode(data.encode("ascii"))


def sign_cookie(payload: dict[str, Any], *, secret: str) -> str:
    """Sign ``payload`` with ``secret`` and return a cookie-safe string.

    Args:
        payload: JSON-serialisable payload.
        secret: HMAC signing key.

    Returns:
        A three-segment cookie value: ``<b64(payload)>.<b64(mac)>``.
    """
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(mac)}"


def verify_cookie(value: str, *, secret: str) -> dict[str, Any]:
    """Verify + decode a cookie produced by :func:`sign_cookie`.

    Args:
        value: The cookie value.
        secret: HMAC signing key.

    Returns:
        The decoded payload.

    Raises:
        AuthError: On malformed / tampered cookies.
    """
    if not value or value.count(".") != 1:
        raise AuthError("malformed session cookie")
    body_b64, mac_b64 = value.split(".", 1)
    body = _b64url_decode(body_b64)
    mac = _b64url_decode(mac_b64)
    expected = hmac.new(secret.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise AuthError("session cookie signature mismatch")
    try:
        decoded: dict[str, Any] = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthError("session cookie payload is not JSON") from exc
    return decoded


SESSION_COOKIE_NAME = _SESSION_COOKIE
"""Exported so routers can reference the cookie name."""

OAUTH_STATE_COOKIE_NAME = _OAUTH_STATE_COOKIE
"""Exported so the OAuth router can reference the cookie name."""
