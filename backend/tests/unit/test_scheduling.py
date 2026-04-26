"""Tests for the slot-matching predicate (Track C — Phase II.2)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.scheduling import (
    LAST_RUN_DEBOUNCE,
    LOCK_STALE_AFTER,
    UserScheduleView,
    is_due,
    next_slot_utc,
)


def _view(
    *,
    frequency: str = "once_daily",
    times: tuple[str, ...] = ("08:00",),
    timezone: str = "UTC",
    last_run: datetime | None = None,
    lock_id: str | None = None,
    lock_started: datetime | None = None,
) -> UserScheduleView:
    return UserScheduleView(
        schedule_frequency=frequency,
        schedule_times_local=times,
        schedule_timezone=timezone,
        last_run_finished_at=last_run,
        current_run_id=lock_id,
        current_run_started_at=lock_started,
    )


def test_is_due_disabled_returns_false() -> None:
    view = _view(frequency="disabled")
    now = datetime(2026, 4, 25, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert is_due(now, view) is False


def test_is_due_within_window_returns_true() -> None:
    view = _view(times=("08:00",))
    now = datetime(2026, 4, 25, 8, 5, tzinfo=ZoneInfo("UTC"))
    assert is_due(now, view) is True


def test_is_due_outside_window_returns_false() -> None:
    view = _view(times=("08:00",))
    now = datetime(2026, 4, 25, 8, 30, tzinfo=ZoneInfo("UTC"))
    assert is_due(now, view) is False


def test_is_due_respects_last_run_debounce() -> None:
    view = _view(
        times=("08:00",),
        last_run=datetime(2026, 4, 25, 7, 30, tzinfo=ZoneInfo("UTC")),
    )
    now = datetime(2026, 4, 25, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert is_due(now, view) is False
    after = now + LAST_RUN_DEBOUNCE
    # Once an hour has elapsed and a fresh slot lands the run is due.
    view_recovered = _view(
        times=("09:00",),
        last_run=datetime(2026, 4, 25, 7, 30, tzinfo=ZoneInfo("UTC")),
    )
    assert is_due(after.replace(hour=9), view_recovered) is True


def test_is_due_respects_lock_until_stale() -> None:
    now = datetime(2026, 4, 25, 8, 0, tzinfo=ZoneInfo("UTC"))
    locked = _view(
        times=("08:00",),
        lock_id="run-1",
        lock_started=now - timedelta(minutes=10),
    )
    assert is_due(now, locked) is False
    stale = _view(
        times=("08:00",),
        lock_id="run-1",
        lock_started=now - LOCK_STALE_AFTER - timedelta(seconds=1),
    )
    assert is_due(now, stale) is True


def test_is_due_handles_cross_timezone() -> None:
    # 08:00 America/New_York on 2026-04-25 → 12:00 UTC.
    view = _view(times=("08:00",), timezone="America/New_York")
    now = datetime(2026, 4, 25, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert is_due(now, view) is True
    early = datetime(2026, 4, 25, 11, 30, tzinfo=ZoneInfo("UTC"))
    assert is_due(early, view) is False


def test_is_due_dst_spring_forward_us() -> None:
    # 2026-03-08 — clocks jump from 02:00 -> 03:00 EST -> EDT.
    view = _view(times=("03:00",), timezone="America/New_York")
    # 03:00 local on the spring-forward day is 07:00 UTC.
    now = datetime(2026, 3, 8, 7, 0, tzinfo=ZoneInfo("UTC"))
    assert is_due(now, view) is True


def test_is_due_dst_fall_back_us() -> None:
    # 2026-11-01 — clocks jump from 02:00 -> 01:00 EDT -> EST.
    # The local "01:30" is ambiguous; zoneinfo's default (fold=0) maps
    # to the EDT instance (05:30 UTC). The predicate fires once per
    # local slot, matching the locked-decision "skipped slots are not
    # re-run" — the second 01:30 (EST, 06:30 UTC) does not re-fire.
    view = _view(times=("01:30",), timezone="America/New_York")
    first = datetime(2026, 11, 1, 5, 30, tzinfo=ZoneInfo("UTC"))
    second = datetime(2026, 11, 1, 6, 30, tzinfo=ZoneInfo("UTC"))
    assert is_due(first, view) is True
    assert is_due(second, view) is False


def test_is_due_twice_daily() -> None:
    view = _view(frequency="twice_daily", times=("08:00", "18:00"))
    morning = datetime(2026, 4, 25, 8, 0, tzinfo=ZoneInfo("UTC"))
    evening = datetime(2026, 4, 25, 18, 0, tzinfo=ZoneInfo("UTC"))
    midday = datetime(2026, 4, 25, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert is_due(morning, view) is True
    assert is_due(evening, view) is True
    assert is_due(midday, view) is False


def test_next_slot_utc_returns_upcoming() -> None:
    view = _view(times=("08:00",))
    now = datetime(2026, 4, 25, 8, 30, tzinfo=ZoneInfo("UTC"))
    expected = datetime(2026, 4, 26, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert next_slot_utc(now, view) == expected


def test_next_slot_utc_disabled_returns_none() -> None:
    view = _view(frequency="disabled")
    now = datetime(2026, 4, 25, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert next_slot_utc(now, view) is None


def test_is_due_skipped_slots_not_re_run() -> None:
    """Track C — Phase II locked decision: skipped slots are not re-run."""
    view = _view(times=("08:00",))
    miss = datetime(2026, 4, 25, 8, 45, tzinfo=ZoneInfo("UTC"))
    assert is_due(miss, view) is False
