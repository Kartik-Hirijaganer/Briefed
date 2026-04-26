"""Quota-aware token-bucket limiter used by the Gmail HTTP client.

Gmail enforces a per-user concurrency + per-project QPS ceiling. The
ingestion pipeline is bursty by nature (list 200 ids, then batch-fetch)
so we throttle outbound requests with a simple refilling token bucket.

The implementation is in-process only — per-Lambda warm-window scope is
sufficient because SQS batch size 1 + ``maximum_batching_window=2s``
(plan §19.15) means at most one ingestion worker runs per account
concurrently.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """Refilling token-bucket rate limiter.

    Attributes:
        capacity: Maximum tokens the bucket can hold.
        refill_rate: Tokens added per second.
        _tokens: Current token balance (internal state).
        _updated_at: Monotonic timestamp of the last refill tick.
        _lock: asyncio lock serialising concurrent ``acquire`` calls.
    """

    capacity: float
    refill_rate: float
    _tokens: float = 0.0
    _updated_at: float = 0.0
    _lock: asyncio.Lock | None = None

    def __post_init__(self) -> None:
        """Initialise the mutable state after dataclass construction."""
        self._tokens = self.capacity
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, cost: float = 1.0) -> None:
        """Block until ``cost`` tokens are available, then deduct them.

        Args:
            cost: Number of tokens the caller needs. Defaults to ``1``.

        Raises:
            ValueError: If ``cost`` exceeds :attr:`capacity`.
        """
        if cost > self.capacity:
            raise ValueError("requested cost exceeds bucket capacity")
        assert self._lock is not None  # set in __post_init__
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= cost:
                    self._tokens -= cost
                    return
                wait_s = (cost - self._tokens) / self.refill_rate
                await asyncio.sleep(wait_s)

    def _refill(self) -> None:
        """Top up the bucket based on elapsed monotonic time."""
        now = time.monotonic()
        elapsed = now - self._updated_at
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
            self._updated_at = now
