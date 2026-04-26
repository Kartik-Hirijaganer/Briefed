"""Pydantic models for the Track C profile + schedule API.

The profile endpoints expose the Track C extensions to ``users``: display
name, email + redaction aliases, schedule cadence, presidio toggle, and
theme preference. ``UserScheduleOut`` exposes the ``next_run_at_utc``
preview which both the UI and a ``GET /me/schedule`` consumer can render.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

ScheduleFrequency = Literal["once_daily", "twice_daily", "disabled"]
"""Allowed schedule cadence values."""

ThemePreference = Literal["system", "light", "dark"]
"""Allowed UI theme values."""

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
"""``HH:MM`` 24-hour format for ``schedule_times_local`` entries."""


def _validate_timezone(value: str) -> str:
    """Return ``value`` unchanged when it is a known IANA zone."""
    if value not in available_timezones():
        raise ValueError(f"unknown timezone: {value!r}")
    return value


def _validate_times(values: tuple[str, ...]) -> tuple[str, ...]:
    """Return ``values`` unchanged when each entry matches ``HH:MM``."""
    for entry in values:
        if not _TIME_RE.fullmatch(entry):
            raise ValueError(f"invalid HH:MM time: {entry!r}")
    return values


def _validate_frequency_consistency(
    frequency: ScheduleFrequency,
    times: tuple[str, ...],
) -> None:
    """Enforce the cadence ↔ slot count invariant."""
    if frequency == "once_daily" and len(times) != 1:
        raise ValueError("once_daily requires exactly one time slot")
    if frequency == "twice_daily" and len(times) != 2:
        raise ValueError("twice_daily requires exactly two time slots")


class UserProfileOut(BaseModel):
    """Current user's profile (Track C — Phase II.3).

    Attributes:
        display_name: Optional display name (consumed by IdentityScrubber).
        email_aliases: Extra email addresses to scrub from prompts.
        redaction_aliases: Free-form strings to scrub from prompts.
        presidio_enabled: Whether Presidio runs ahead of regex scrubbing.
        theme_preference: Server-side mirror of the user's UI theme.
        schedule_frequency: Cadence — ``once_daily`` / ``twice_daily`` /
            ``disabled``.
        schedule_times_local: ``HH:MM`` slots in :attr:`schedule_timezone`.
        schedule_timezone: IANA timezone name.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    display_name: str | None = None
    email_aliases: tuple[str, ...] = Field(default_factory=tuple)
    redaction_aliases: tuple[str, ...] = Field(default_factory=tuple)
    presidio_enabled: bool = True
    theme_preference: ThemePreference = "system"
    schedule_frequency: ScheduleFrequency = "once_daily"
    schedule_times_local: tuple[str, ...] = Field(default=("08:00",))
    schedule_timezone: str = "UTC"


class UserProfilePatchRequest(BaseModel):
    """Partial update body for ``PATCH /profile/me``.

    Omitted fields keep their current values. Email aliases are
    validated as RFC-5322 (IDN-aware via :class:`pydantic.EmailStr`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    email_aliases: tuple[EmailStr, ...] | None = Field(default=None)
    redaction_aliases: tuple[str, ...] | None = Field(default=None)
    presidio_enabled: bool | None = Field(default=None)
    theme_preference: ThemePreference | None = Field(default=None)


class UserScheduleOut(BaseModel):
    """Schedule view of the user's profile.

    ``next_run_at_utc`` is computed via :func:`app.core.scheduling.next_slot_utc`
    so the UI's "next run" preview agrees with the fanout filter.
    """

    model_config = ConfigDict(frozen=True)

    schedule_frequency: ScheduleFrequency
    schedule_times_local: tuple[str, ...]
    schedule_timezone: str
    next_run_at_utc: datetime | None = None


class UserSchedulePatchRequest(BaseModel):
    """Partial update body for ``PATCH /profile/me/schedule``.

    Validation rules:
    * Each :attr:`schedule_times_local` entry must match ``HH:MM``.
    * :attr:`schedule_timezone` must be in :func:`zoneinfo.available_timezones`.
    * The frequency / slot-count invariant is checked when *both* are
      provided in the same request, or against the existing row when
      only one side is sent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule_frequency: ScheduleFrequency | None = Field(default=None)
    schedule_times_local: tuple[str, ...] | None = Field(default=None)
    schedule_timezone: str | None = Field(default=None)

    @field_validator("schedule_times_local")
    @classmethod
    def _check_times(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        """Ensure each provided time slot is ``HH:MM``."""
        if value is None:
            return None
        return _validate_times(value)

    @field_validator("schedule_timezone")
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        """Ensure the timezone is a known IANA label."""
        if value is None:
            return None
        return _validate_timezone(value)

    @model_validator(mode="after")
    def _check_consistency(self) -> UserSchedulePatchRequest:
        """Enforce cadence/slot-count consistency when both fields are sent."""
        if self.schedule_frequency is not None and self.schedule_times_local is not None:
            _validate_frequency_consistency(
                self.schedule_frequency,
                self.schedule_times_local,
            )
        return self


__all__ = [
    "ScheduleFrequency",
    "ThemePreference",
    "UserProfileOut",
    "UserProfilePatchRequest",
    "UserScheduleOut",
    "UserSchedulePatchRequest",
]
