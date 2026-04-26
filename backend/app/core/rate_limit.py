"""In-process rate limiter for the Phase 8 manual-run cap (plan §19.16, §20.2).

Plan §20.2 explicitly defers a dedicated ``manual_run_quota`` table; the
in-memory counter described there is what this module provides. Each
Lambda warm window owns its own counter dictionary keyed by
``user_id``; we accept that a cold-start resets it (the practical
ceiling is much smaller than the SQS+LLM cost a determined abuser
would pay anyway, and the per-account ``daily_budget_*`` already caps
spend per plan §20.2).

Test surface lives in
``backend/tests/unit/test_manual_run_rate_limit.py``; the API wires the
limiter via :func:`enforce_manual_run` from the router for plan §19.16
Phase 8 ("rate-limit test on `POST /api/v1/runs`").
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import HTTPException, status

from app.core.config import get_settings


@dataclass
class _Bucket:
    """Per-user sliding-window counter."""

    timestamps: list[float] = field(default_factory=list)


@dataclass
class ManualRunRateLimiter:
    """Sliding-window limiter for manual-run triggers.

    The window is rolling 24 hours (86 400 s) per plan §19.16.
    Concurrent calls from the same warm Lambda are serialized through a
    short critical section; cross-instance races are accepted (we ship
    one user, low-volume).
    """

    capacity: int
    window_seconds: float = 86_400.0
    _buckets: dict[UUID, _Bucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, user_id: UUID, *, now: float | None = None) -> None:
        """Record one trigger or raise :class:`fastapi.HTTPException`.

        Args:
            user_id: Owner attempting the manual run.
            now: Monotonic-style epoch seconds; injected by tests.

        Raises:
            HTTPException: ``429`` with ``Retry-After`` set when the
                user has already spent ``capacity`` triggers in the
                rolling window.
        """
        ts = time.time() if now is None else now
        cutoff = ts - self.window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(user_id, _Bucket())
            bucket.timestamps = [t for t in bucket.timestamps if t >= cutoff]
            if len(bucket.timestamps) >= self.capacity:
                oldest = bucket.timestamps[0]
                retry_after = max(1, int(oldest + self.window_seconds - ts))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"manual run quota exceeded "
                        f"({len(bucket.timestamps)}/{self.capacity} in 24h)"
                    ),
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.timestamps.append(ts)


_LIMITER: ManualRunRateLimiter | None = None
"""Module-level singleton; survives the Lambda warm window."""

_SINGLETON_LOCK = threading.Lock()
"""Guards :data:`_LIMITER` initialization across concurrent invocations."""


def get_manual_run_limiter() -> ManualRunRateLimiter:
    """Return the process-wide manual-run limiter.

    Returns:
        A shared :class:`ManualRunRateLimiter` whose capacity comes from
        :attr:`Settings.manual_run_daily_cap`.
    """
    global _LIMITER  # noqa: PLW0603 — module-level singleton, intentional.
    if _LIMITER is None:
        with _SINGLETON_LOCK:
            if _LIMITER is None:
                _LIMITER = ManualRunRateLimiter(
                    capacity=get_settings().manual_run_daily_cap,
                )
    return _LIMITER


def reset_manual_run_limiter() -> None:
    """Drop the cached limiter; tests use this to start clean."""
    global _LIMITER  # noqa: PLW0603 — see :func:`get_manual_run_limiter`.
    _LIMITER = None


def enforce_manual_run(user_id: UUID) -> None:
    """Check the per-user manual-run cap.

    Args:
        user_id: Owner attempting the manual run.

    Raises:
        HTTPException: When the cap has been exceeded.
    """
    get_manual_run_limiter().check(user_id)


__all__ = [
    "ManualRunRateLimiter",
    "enforce_manual_run",
    "get_manual_run_limiter",
    "reset_manual_run_limiter",
]
