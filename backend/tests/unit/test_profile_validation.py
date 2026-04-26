"""Tests for the Track C profile + schedule schemas (Phase II.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.profile import (
    UserProfilePatchRequest,
    UserSchedulePatchRequest,
)


def test_profile_patch_accepts_minimal_payload() -> None:
    payload = UserProfilePatchRequest()
    assert payload.model_dump(exclude_unset=True) == {}


def test_profile_patch_accepts_idn_email() -> None:
    payload = UserProfilePatchRequest(email_aliases=("alt@example.com",))
    assert payload.email_aliases == ("alt@example.com",)


def test_profile_patch_rejects_bad_email() -> None:
    with pytest.raises(ValidationError):
        UserProfilePatchRequest(email_aliases=("not-an-email",))


def test_profile_patch_validates_theme_enum() -> None:
    with pytest.raises(ValidationError):
        UserProfilePatchRequest(theme_preference="solarized")  # type: ignore[arg-type]


def test_schedule_patch_rejects_bad_time_format() -> None:
    with pytest.raises(ValidationError):
        UserSchedulePatchRequest(schedule_times_local=("8:00",))


def test_schedule_patch_rejects_unknown_timezone() -> None:
    with pytest.raises(ValidationError):
        UserSchedulePatchRequest(schedule_timezone="Mars/Olympus_Mons")


def test_schedule_patch_enforces_length_consistency() -> None:
    with pytest.raises(ValidationError):
        UserSchedulePatchRequest(
            schedule_frequency="twice_daily",
            schedule_times_local=("08:00",),
        )


def test_schedule_patch_allows_valid_twice_daily() -> None:
    payload = UserSchedulePatchRequest(
        schedule_frequency="twice_daily",
        schedule_times_local=("08:00", "18:00"),
        schedule_timezone="America/New_York",
    )
    assert payload.schedule_frequency == "twice_daily"
    assert payload.schedule_times_local == ("08:00", "18:00")


def test_schedule_patch_allows_disabled_with_empty_times() -> None:
    # Disabled cadence accepts any slot count (including unchanged).
    payload = UserSchedulePatchRequest(schedule_frequency="disabled")
    assert payload.schedule_frequency == "disabled"
