"""Slot-matching predicate for the daily fan-out (Track C — Phase II.2).

The single source of truth for "should this user run right now?" is
:func:`is_due`. Both the fan-out filter and the "next run preview" UI
consume it — branching the predicate would let the UI lie about when
the next run will land.

Slot precision is ``±7.5min``. EventBridge fires every 15 minutes UTC
so each candidate slot is reachable in exactly one tick.

Behavior:
* ``schedule_frequency='disabled'`` → never due.
* Last run finished within the trailing hour → suppress (debounce).
* ``current_run_id IS NOT NULL`` and the lock is fresh (< 30 min) →
  another tick is in flight; skip. Stale locks (≥ 30 min) release
  automatically so a crashed worker does not wedge the user forever.
* Skipped slots are not re-run. If the worker is offline at 08:00 we
  do not fire late at 08:45 — the user waits for the next natural
  slot. Predictable beats eager for a recommend-only system.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence


SLOT_HALF_WINDOW = timedelta(minutes=7, seconds=30)
"""Half-width of the slot-matching window. EventBridge cadence is 15min,
so a slot at ``HH:MM`` matches any tick in ``[HH:MM-7:30, HH:MM+7:30]``."""

LAST_RUN_DEBOUNCE = timedelta(hours=1)
"""Don't fire a second time within this trailing window."""

LOCK_STALE_AFTER = timedelta(minutes=30)
"""Idempotency lock auto-releases after this many minutes — covers the
crash-mid-pipeline case without letting a stuck user starve."""


@dataclass(frozen=True)
class UserScheduleView:
    """Subset of ``users`` columns the slot predicate consumes.

    Attributes:
        schedule_frequency: ``once_daily`` / ``twice_daily`` / ``disabled``.
        schedule_times_local: ``HH:MM`` slots in :attr:`schedule_timezone`.
        schedule_timezone: IANA timezone label.
        last_run_finished_at: UTC of the most recent successful run.
        current_run_id: Active idempotency lock value, if any.
        current_run_started_at: UTC the lock was acquired.
    """

    schedule_frequency: str
    schedule_times_local: Sequence[str]
    schedule_timezone: str
    last_run_finished_at: datetime | None
    current_run_id: str | None
    current_run_started_at: datetime | None


def _ensure_aware(value: datetime) -> datetime:
    """Return the value with a UTC tzinfo when naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo("UTC"))
    return value


def _resolve_zone(name: str) -> ZoneInfo:
    """Return the user's timezone, falling back to UTC on bad data."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _parse_slot(value: str) -> tuple[int, int] | None:
    """Parse an ``HH:MM`` slot into its ``(hour, minute)`` components.

    Args:
        value: Raw slot string from the user profile.

    Returns:
        ``(hour, minute)`` when the string is a valid ``HH:MM``; ``None``
        when malformed (the caller skips bad slots rather than raise so
        a corrupted profile cannot wedge the fan-out).
    """
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour, minute


def _candidate_utc_slots(
    *,
    now_utc: datetime,
    profile: UserScheduleView,
) -> list[datetime]:
    """Project local-time slots onto the UTC day around ``now_utc``.

    A slot is materialized for the current local day, the prior local
    day, and the next local day so a slot near midnight UTC still
    matches when the local zone wraps the date boundary.

    Args:
        now_utc: Reference UTC instant.
        profile: The user's schedule view.

    Returns:
        UTC datetimes for every parseable slot on the surrounding days.
    """
    zone = _resolve_zone(profile.schedule_timezone)
    now_local = now_utc.astimezone(zone)
    candidates: list[datetime] = []
    for offset_days in (-1, 0, 1):
        local_day = (now_local + timedelta(days=offset_days)).date()
        for raw in profile.schedule_times_local:
            parsed = _parse_slot(raw)
            if parsed is None:
                continue
            hour, minute = parsed
            local_dt = datetime(
                year=local_day.year,
                month=local_day.month,
                day=local_day.day,
                hour=hour,
                minute=minute,
                tzinfo=zone,
            )
            candidates.append(local_dt.astimezone(ZoneInfo("UTC")))
    return candidates


def is_due(now_utc: datetime, profile: UserScheduleView) -> bool:
    """Return ``True`` when the user should run in the current tick.

    See module docstring for behavior. The same predicate backs both
    the fan-out filter and the "next run preview" — never branch.

    Args:
        now_utc: Reference UTC instant (typically the EventBridge tick).
        profile: The user's schedule view.

    Returns:
        ``True`` when a slot, the debounce, and the lock all permit a
        run; ``False`` otherwise.
    """
    if profile.schedule_frequency == "disabled":
        return False

    now_utc_aware = _ensure_aware(now_utc)

    if profile.last_run_finished_at is not None:
        last = _ensure_aware(profile.last_run_finished_at)
        if now_utc_aware - last < LAST_RUN_DEBOUNCE:
            return False

    if profile.current_run_id is not None:
        started = (
            _ensure_aware(profile.current_run_started_at)
            if profile.current_run_started_at is not None
            else None
        )
        if started is None or now_utc_aware - started < LOCK_STALE_AFTER:
            return False

    for candidate in _candidate_utc_slots(now_utc=now_utc_aware, profile=profile):
        delta = abs(candidate - now_utc_aware)
        if delta <= SLOT_HALF_WINDOW:
            return True
    return False


def next_slot_utc(now_utc: datetime, profile: UserScheduleView) -> datetime | None:
    """Return the next UTC datetime the user is scheduled to run.

    Used by the Settings UI to render a "next run" preview. Returns
    ``None`` when the schedule is disabled or every parseable slot is
    in the past for some reason (e.g. empty ``schedule_times_local``).

    Args:
        now_utc: Reference UTC instant.
        profile: The user's schedule view.

    Returns:
        The earliest UTC slot strictly after ``now_utc``, or ``None``.
    """
    if profile.schedule_frequency == "disabled":
        return None
    now_utc_aware = _ensure_aware(now_utc)
    zone = _resolve_zone(profile.schedule_timezone)
    now_local = now_utc_aware.astimezone(zone)

    upcoming: list[datetime] = []
    for offset_days in (0, 1, 2):
        local_day = (now_local + timedelta(days=offset_days)).date()
        for raw in profile.schedule_times_local:
            parsed = _parse_slot(raw)
            if parsed is None:
                continue
            hour, minute = parsed
            local_dt = datetime(
                year=local_day.year,
                month=local_day.month,
                day=local_day.day,
                hour=hour,
                minute=minute,
                tzinfo=zone,
            )
            candidate = local_dt.astimezone(ZoneInfo("UTC"))
            if candidate > now_utc_aware:
                upcoming.append(candidate)
    if not upcoming:
        return None
    return min(upcoming)


__all__ = [
    "LAST_RUN_DEBOUNCE",
    "LOCK_STALE_AFTER",
    "SLOT_HALF_WINDOW",
    "UserScheduleView",
    "is_due",
    "next_slot_utc",
]
