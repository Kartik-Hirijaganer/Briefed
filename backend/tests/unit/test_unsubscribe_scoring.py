"""Unit tests for the Phase 5 scorer + `UnsubscribeDecision` schema (plan §14 Phase 5)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.llm.schemas import UnsubscribeDecision
from app.services.unsubscribe.aggregator import SenderStats, score_sender


def _stats(
    *,
    frequency: int,
    engagement: str,
    waste: str,
    classified: int = 10,
) -> SenderStats:
    return SenderStats(
        sender_email="x@y.example",
        sender_domain="y.example",
        frequency_30d=frequency,
        positive_count=0,
        waste_count=0,
        classified_total=classified,
        engagement_score=Decimal(engagement),
        waste_rate=Decimal(waste),
        list_unsubscribe=None,
        last_email_at=None,
        recent_subjects=(),
    )


def test_score_all_three_hits() -> None:
    stats = _stats(frequency=22, engagement="0.05", waste="0.80")
    score = score_sender(stats)
    assert score.hit_count == 3
    assert score.noisy is True
    assert score.low_value is True
    assert score.disengaged is True
    assert score.labels == ("noisy", "low_value", "disengaged")


def test_score_two_of_three_flags_borderline() -> None:
    # noisy + low_value but engagement above the ceiling
    stats = _stats(frequency=10, engagement="0.40", waste="0.75")
    score = score_sender(stats)
    assert score.hit_count == 2
    assert score.noisy is True
    assert score.low_value is True
    assert score.disengaged is False


def test_score_single_hit_skipped() -> None:
    stats = _stats(frequency=10, engagement="0.70", waste="0.10")
    score = score_sender(stats)
    assert score.hit_count == 1
    assert score.labels == ("noisy",)


def test_score_zero_classified_suppresses_disengaged() -> None:
    # With no classifications, we cannot call the user "disengaged".
    stats = _stats(
        frequency=10,
        engagement="0.00",
        waste="0.00",
        classified=0,
    )
    score = score_sender(stats)
    assert score.disengaged is False
    assert score.noisy is True


def test_unsubscribe_decision_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        UnsubscribeDecision.model_validate(
            {
                "should_recommend": True,
                "confidence": 0.9,
                "category": "promotional",
                "rationale": "noisy sender",
                "action_url": "https://evil.example",
            },
        )


def test_unsubscribe_decision_rejects_bad_category() -> None:
    with pytest.raises(ValidationError):
        UnsubscribeDecision.model_validate(
            {
                "should_recommend": True,
                "confidence": 0.9,
                "category": "hot-garbage",
                "rationale": "n/a",
            },
        )


def test_unsubscribe_decision_trims_whitespace() -> None:
    dec = UnsubscribeDecision.model_validate(
        {
            "should_recommend": False,
            "confidence": 0.66,
            "category": "notification",
            "rationale": "  banking notices; stay subscribed.  ",
        },
    )
    assert dec.rationale == "banking notices; stay subscribed."
