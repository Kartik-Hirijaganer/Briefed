"""Unit tests for the manual-run rate limiter (plan §19.16, §20.2)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.core.rate_limit import ManualRunRateLimiter


def _user() -> uuid.UUID:
    return uuid.uuid4()


def test_under_cap_passes() -> None:
    limiter = ManualRunRateLimiter(capacity=3)
    user = _user()
    for _ in range(3):
        limiter.check(user, now=1_000.0)


def test_over_cap_raises_429() -> None:
    limiter = ManualRunRateLimiter(capacity=2)
    user = _user()
    limiter.check(user, now=1_000.0)
    limiter.check(user, now=1_000.0)
    with pytest.raises(HTTPException) as info:
        limiter.check(user, now=1_000.0)
    assert info.value.status_code == 429
    assert info.value.headers is not None
    assert "Retry-After" in info.value.headers


def test_window_rolls_off_after_24h() -> None:
    limiter = ManualRunRateLimiter(capacity=1, window_seconds=86_400.0)
    user = _user()
    limiter.check(user, now=0.0)
    with pytest.raises(HTTPException):
        limiter.check(user, now=10.0)
    # Just past the 24h window — the original timestamp evicts.
    limiter.check(user, now=86_500.0)


def test_per_user_buckets_are_independent() -> None:
    limiter = ManualRunRateLimiter(capacity=1)
    a, b = _user(), _user()
    limiter.check(a, now=1_000.0)
    # User b should not be blocked by user a's quota.
    limiter.check(b, now=1_000.0)
    with pytest.raises(HTTPException):
        limiter.check(a, now=1_000.0)


def test_retry_after_reflects_oldest_timestamp() -> None:
    limiter = ManualRunRateLimiter(capacity=1, window_seconds=100.0)
    user = _user()
    limiter.check(user, now=0.0)
    with pytest.raises(HTTPException) as info:
        limiter.check(user, now=10.0)
    assert info.value.headers is not None
    retry = int(info.value.headers["Retry-After"])
    # Oldest=0, window=100 → caller should retry around 90s from now (10).
    assert 80 <= retry <= 100
