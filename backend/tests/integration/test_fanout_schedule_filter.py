"""Verify ``is_due`` is the single source of truth for the fanout filter.

Track C — Phase II.4: the fan-out handler must defer to
:func:`app.core.scheduling.is_due` so the UI's "next run" preview agrees
with the work that actually lands on the queue.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConnectedAccount, User
from app.workers.handlers.fanout import FanoutDeps, run_fanout


class _FakeSqs:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        self.sent.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": str(len(self.sent))}


async def _seed(
    session: AsyncSession,
    *,
    schedule_frequency: str = "once_daily",
    schedule_times_local: list[str] | None = None,
    schedule_timezone: str = "UTC",
    last_run_finished_at: datetime | None = None,
    current_run_id: str | None = None,
    current_run_started_at: datetime | None = None,
) -> User:
    user = User(
        email="o@x.com",
        tz="UTC",
        status="active",
        schedule_frequency=schedule_frequency,
        schedule_times_local=schedule_times_local or ["08:00"],
        schedule_timezone=schedule_timezone,
        last_run_finished_at=last_run_finished_at,
        current_run_id=current_run_id,
        current_run_started_at=current_run_started_at,
    )
    session.add(user)
    await session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="o@x.com",
        status="active",
        auto_scan_enabled=True,
    )
    session.add(account)
    await session.commit()
    return user


async def test_fanout_skips_users_outside_slot_window(
    test_session: AsyncSession,
) -> None:
    await _seed(test_session, schedule_times_local=["08:00"])
    sqs = _FakeSqs()
    deps = FanoutDeps(
        session=test_session,
        sqs=sqs,
        ingest_queue_url="https://sqs.local/ingest",
    )
    # Tick lands well outside the 08:00 ±7:30 window.
    with patch(
        "app.workers.handlers.fanout.utcnow",
        return_value=datetime(2026, 4, 25, 8, 30, tzinfo=ZoneInfo("UTC")),
    ):
        enqueued = await run_fanout(deps=deps)
    assert enqueued == 0
    assert sqs.sent == []


async def test_fanout_runs_user_in_slot_and_acquires_lock(
    test_session: AsyncSession,
) -> None:
    user = await _seed(test_session, schedule_times_local=["08:00"])
    sqs = _FakeSqs()
    deps = FanoutDeps(
        session=test_session,
        sqs=sqs,
        ingest_queue_url="https://sqs.local/ingest",
    )
    with patch(
        "app.workers.handlers.fanout.utcnow",
        return_value=datetime(2026, 4, 25, 8, 5, tzinfo=ZoneInfo("UTC")),
    ):
        enqueued = await run_fanout(deps=deps)
    assert enqueued == 1
    assert len(sqs.sent) == 1
    refreshed = await test_session.get(User, user.id)
    assert refreshed is not None
    assert refreshed.current_run_id is not None
    assert refreshed.current_run_started_at is not None


async def test_fanout_skips_locked_user(test_session: AsyncSession) -> None:
    now = datetime(2026, 4, 25, 8, 5, tzinfo=ZoneInfo("UTC"))
    await _seed(
        test_session,
        schedule_times_local=["08:00"],
        current_run_id="run-1",
        current_run_started_at=now - timedelta(minutes=10),
    )
    sqs = _FakeSqs()
    deps = FanoutDeps(
        session=test_session,
        sqs=sqs,
        ingest_queue_url="https://sqs.local/ingest",
    )
    with patch("app.workers.handlers.fanout.utcnow", return_value=now):
        enqueued = await run_fanout(deps=deps)
    assert enqueued == 0


async def test_fanout_runs_after_stale_lock(test_session: AsyncSession) -> None:
    now = datetime(2026, 4, 25, 8, 5, tzinfo=ZoneInfo("UTC"))
    await _seed(
        test_session,
        schedule_times_local=["08:00"],
        current_run_id="run-1",
        current_run_started_at=now - timedelta(minutes=45),
    )
    sqs = _FakeSqs()
    deps = FanoutDeps(
        session=test_session,
        sqs=sqs,
        ingest_queue_url="https://sqs.local/ingest",
    )
    with patch("app.workers.handlers.fanout.utcnow", return_value=now):
        enqueued = await run_fanout(deps=deps)
    assert enqueued == 1


async def test_fanout_skips_disabled_user(test_session: AsyncSession) -> None:
    await _seed(test_session, schedule_frequency="disabled")
    sqs = _FakeSqs()
    deps = FanoutDeps(
        session=test_session,
        sqs=sqs,
        ingest_queue_url="https://sqs.local/ingest",
    )
    enqueued = await run_fanout(deps=deps)
    assert enqueued == 0
