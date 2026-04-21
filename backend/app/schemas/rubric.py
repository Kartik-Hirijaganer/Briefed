"""Pydantic boundary models for the rubric API (plan §14 Phase 2).

The API surface is intentionally thin: list + create + update + delete.
Each endpoint accepts/returns either :class:`RubricRuleIn` or
:class:`RubricRuleOut`, which are frozen so the request body cannot be
mutated mid-handler.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_MATCH_KEYS = frozenset(
    {
        "from_domain",
        "from_email",
        "subject_regex",
        "has_label",
        "list_unsubscribe_present",
        "header_equals",
    },
)

_ALLOWED_LABELS = frozenset(
    {
        "must_read",
        "good_to_read",
        "ignore",
        "waste",
        "needs_review",
    },
)


class RubricRuleIn(BaseModel):
    """Request body for POST / PUT.

    Attributes:
        priority: Higher wins. Defaults to ``100``.
        match: Predicate dict; keys limited to
            :data:`_ALLOWED_MATCH_KEYS`.
        action: Verdict dict; must contain ``label`` ∈
            :data:`_ALLOWED_LABELS` and ``confidence`` ∈ ``[0, 1]``.
        active: Soft-delete switch. Defaults to ``True``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    priority: int = Field(default=100, ge=0, le=100_000)
    match: dict[str, Any] = Field(..., min_length=1)
    action: dict[str, Any] = Field(...)
    active: bool = Field(default=True)

    @field_validator("match")
    @classmethod
    def _validate_match(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Reject unknown predicate keys at the request boundary."""
        unknown = set(value) - _ALLOWED_MATCH_KEYS
        if unknown:
            raise ValueError(f"match contains unsupported keys: {sorted(unknown)}")
        return value

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Enforce required action keys + value ranges."""
        label = value.get("label")
        if label not in _ALLOWED_LABELS:
            raise ValueError(f"action.label must be one of {sorted(_ALLOWED_LABELS)}")
        confidence = value.get("confidence", 0.9)
        try:
            conf = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("action.confidence must be a number in [0, 1]") from exc
        if not 0.0 <= conf <= 1.0:
            raise ValueError("action.confidence must be in [0, 1]")
        for flag_name in ("is_newsletter", "is_job_candidate"):
            flag_value = value.get(flag_name)
            if flag_value is not None and not isinstance(flag_value, bool):
                raise ValueError(f"action.{flag_name} must be a boolean when present")
        return value


class RubricRuleOut(BaseModel):
    """Response body for list / create / update.

    Attributes:
        id: Rule primary key.
        priority: Priority plumbed through from the DB row.
        match: Predicate dict.
        action: Verdict dict.
        version: Monotonically increasing version.
        active: Soft-delete switch.
        created_at: When the rule was first inserted.
        updated_at: Last-modified timestamp.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    priority: int
    match: dict[str, Any]
    action: dict[str, Any]
    version: int
    active: bool
    created_at: datetime
    updated_at: datetime


class RubricRulesListResponse(BaseModel):
    """Envelope for ``GET /rubric``.

    Attributes:
        rules: Every :class:`RubricRuleOut` owned by the caller,
            ordered by ``priority DESC``.
    """

    model_config = ConfigDict(frozen=True)

    rules: tuple[RubricRuleOut, ...] = Field(default=())


__all__ = [
    "RubricRuleIn",
    "RubricRuleOut",
    "RubricRulesListResponse",
]
