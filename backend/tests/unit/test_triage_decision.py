"""Unit tests for the TriageDecision Pydantic schema (plan §14 Phase 2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.schemas import TriageDecision


def test_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TriageDecision.model_validate(
            {
                "category": "must_read",
                "confidence": 0.9,
                "reasons_short": "ok",
                "unexpected_field": 1,
            },
        )


def test_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        TriageDecision(
            category="must_read",
            confidence=1.5,
            reasons_short="ok",
        )


def test_trims_reasons_short() -> None:
    decision = TriageDecision(
        category="must_read",
        confidence=0.9,
        reasons_short="   trimmed   ",
    )
    assert decision.reasons_short == "trimmed"


def test_enforces_category_enum() -> None:
    with pytest.raises(ValidationError):
        TriageDecision.model_validate(
            {
                "category": "bogus",
                "confidence": 0.9,
                "reasons_short": "ok",
            },
        )


def test_rejects_too_long_reasons() -> None:
    with pytest.raises(ValidationError):
        TriageDecision.model_validate(
            {
                "category": "must_read",
                "confidence": 0.9,
                "reasons_short": "x" * 500,
            },
        )
