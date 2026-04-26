"""Tests for the signed-cookie helpers in :mod:`app.api.session`."""

from __future__ import annotations

import pytest

from app.api.session import sign_cookie, verify_cookie
from app.core.errors import AuthError


def test_sign_and_verify_roundtrip() -> None:
    payload = {"user_id": "abc", "ttl": 3600}
    cookie = sign_cookie(payload, secret="k")
    assert verify_cookie(cookie, secret="k") == payload


def test_bad_secret_raises() -> None:
    cookie = sign_cookie({"x": 1}, secret="real")
    with pytest.raises(AuthError):
        verify_cookie(cookie, secret="forged")


def test_malformed_cookie_raises() -> None:
    with pytest.raises(AuthError):
        verify_cookie("no-dot", secret="k")
    with pytest.raises(AuthError):
        verify_cookie("", secret="k")


def test_tampered_body_raises() -> None:
    cookie = sign_cookie({"x": 1}, secret="k")
    body, sig = cookie.split(".", 1)
    with pytest.raises(AuthError):
        verify_cookie(body + "junk." + sig, secret="k")


def test_non_json_body_raises() -> None:
    # Build a cookie whose body is not JSON, but is correctly signed.
    import base64
    import hmac as _hmac
    from hashlib import sha256

    def _b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")

    body = b"\xff\xff\xff\xff"  # invalid UTF-8
    mac = _hmac.new(b"k", body, sha256).digest()
    cookie = f"{_b64(body)}.{_b64(mac)}"
    with pytest.raises(AuthError):
        verify_cookie(cookie, secret="k")
