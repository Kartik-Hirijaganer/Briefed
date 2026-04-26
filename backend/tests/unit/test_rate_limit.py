"""Tests for the Gmail token-bucket limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.gmail.ratelimit import TokenBucket


async def test_bucket_allows_burst_up_to_capacity() -> None:
    bucket = TokenBucket(capacity=3.0, refill_rate=1.0)
    started = time.monotonic()
    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()
    assert time.monotonic() - started < 0.1


async def test_bucket_throttles_once_drained() -> None:
    bucket = TokenBucket(capacity=1.0, refill_rate=10.0)
    await bucket.acquire()
    started = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - started
    assert elapsed >= 0.08, elapsed


async def test_bucket_rejects_oversized_cost() -> None:
    bucket = TokenBucket(capacity=2.0, refill_rate=1.0)
    with pytest.raises(ValueError):
        await bucket.acquire(cost=5.0)


async def test_bucket_serialises_concurrent_callers() -> None:
    bucket = TokenBucket(capacity=2.0, refill_rate=100.0)

    async def call() -> None:
        await bucket.acquire()

    await asyncio.gather(*(call() for _ in range(5)))
