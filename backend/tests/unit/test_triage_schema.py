"""Unit tests for triage/v2 runtime schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.schemas import TriageDecision


def test_triage_v2_accepts_three_categories_only() -> None:
    decision = TriageDecision(
        category="must_read",
        confidence=0.9,
        reasons_short="Direct ask.",
        is_newsletter=False,
    )

    assert decision.category == "must_read"


@pytest.mark.parametrize("category", ["waste", "needs_review"])
def test_triage_v2_rejects_legacy_categories(category: str) -> None:
    with pytest.raises(ValidationError):
        TriageDecision(
            category=category,
            confidence=0.9,
            reasons_short="Legacy label.",
        )


def test_triage_v2_rejects_job_candidate_flag() -> None:
    with pytest.raises(ValidationError):
        TriageDecision.model_validate(
            {
                "category": "good_to_read",
                "confidence": 0.9,
                "reasons_short": "Recruiter note.",
                "is_job_candidate": True,
            },
        )
