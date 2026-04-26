"""Unit tests for :mod:`app.services.jobs.predicate`.

Covers the full operator matrix described in the module docstring,
plus guardrails around unknown keys and malformed values.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.jobs import predicate
from app.services.jobs.predicate import (
    JobCandidate,
    PredicateError,
    evaluate,
    evaluate_many,
)


def _candidate(**overrides: object) -> JobCandidate:
    base: dict[str, object] = {
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "location": "Remote — US",
        "remote": True,
        "comp_min": 180_000,
        "comp_max": 220_000,
        "currency": "USD",
        "seniority": "senior",
        "match_score": 0.88,
    }
    base.update(overrides)
    return JobCandidate(**base)  # type: ignore[arg-type]


def test_empty_predicate_passes() -> None:
    assert evaluate({}, _candidate()) is True


def test_unknown_key_raises() -> None:
    with pytest.raises(PredicateError):
        evaluate({"min_salary": 100}, _candidate())


def test_min_comp_passes_when_ceiling_meets_floor() -> None:
    assert evaluate({"min_comp": 200_000}, _candidate()) is True
    assert evaluate({"min_comp": 250_000}, _candidate()) is False


def test_min_comp_rejects_row_with_unknown_ceiling() -> None:
    candidate = _candidate(comp_max=None)
    assert evaluate({"min_comp": 100_000}, candidate) is False


def test_max_comp_passes_when_floor_is_under_ceiling() -> None:
    assert evaluate({"max_comp": 300_000}, _candidate()) is True
    assert evaluate({"max_comp": 150_000}, _candidate()) is False


def test_max_comp_rejects_row_with_unknown_floor() -> None:
    assert evaluate({"max_comp": 300_000}, _candidate(comp_min=None)) is False


def test_currency_case_insensitive() -> None:
    assert evaluate({"currency": "usd"}, _candidate()) is True
    assert evaluate({"currency": "GBP"}, _candidate()) is False
    assert evaluate({"currency": "USD"}, _candidate(currency=None)) is False


def test_remote_required_tri_state() -> None:
    assert evaluate({"remote_required": True}, _candidate(remote=True)) is True
    assert evaluate({"remote_required": True}, _candidate(remote=None)) is False
    assert evaluate({"remote_required": True}, _candidate(remote=False)) is False

    # When remote_required is False we accept remote=False OR remote=None.
    assert evaluate({"remote_required": False}, _candidate(remote=False)) is True
    assert evaluate({"remote_required": False}, _candidate(remote=None)) is True
    assert evaluate({"remote_required": False}, _candidate(remote=True)) is False


def test_location_any_case_insensitive_substring() -> None:
    assert evaluate({"location_any": ["us", "canada"]}, _candidate()) is True
    assert evaluate({"location_any": ["London"]}, _candidate(location="Berlin")) is False
    assert evaluate({"location_any": ["Anywhere"]}, _candidate(location=None)) is False


def test_location_none_blocks_matching_substring() -> None:
    assert (
        evaluate(
            {"location_none": ["India"]},
            _candidate(location="Bangalore, India"),
        )
        is False
    )
    assert (
        evaluate(
            {"location_none": ["India"]},
            _candidate(location="Remote — US"),
        )
        is True
    )
    assert evaluate({"location_none": ["India"]}, _candidate(location=None)) is True


def test_title_keywords_any_and_none() -> None:
    assert evaluate({"title_keywords_any": ["backend", "platform"]}, _candidate()) is True
    assert evaluate({"title_keywords_any": ["frontend"]}, _candidate()) is False
    assert evaluate({"title_keywords_none": ["frontend"]}, _candidate()) is True
    assert (
        evaluate(
            {"title_keywords_none": ["backend"]},
            _candidate(),
        )
        is False
    )


def test_seniority_in_allows_enum_set() -> None:
    assert evaluate({"seniority_in": ["senior", "staff"]}, _candidate()) is True
    assert evaluate({"seniority_in": ["staff"]}, _candidate()) is False
    assert (
        evaluate(
            {"seniority_in": ["senior"]},
            _candidate(seniority=None),
        )
        is False
    )


def test_min_confidence_respects_match_score() -> None:
    assert evaluate({"min_confidence": 0.85}, _candidate()) is True
    assert evaluate({"min_confidence": 0.95}, _candidate()) is False
    # Decimal inputs round-trip cleanly — filter rows can come from JSONB.
    assert evaluate({"min_confidence": Decimal("0.8")}, _candidate()) is True


def test_min_confidence_out_of_range_raises() -> None:
    with pytest.raises(PredicateError):
        evaluate({"min_confidence": 1.5}, _candidate())


def test_min_confidence_rejects_non_numbers() -> None:
    with pytest.raises(PredicateError):
        evaluate({"min_confidence": True}, _candidate())
    with pytest.raises(PredicateError):
        evaluate({"min_confidence": "0.7"}, _candidate())


def test_evaluate_many_requires_all_filters() -> None:
    preds = [
        {"min_comp": 150_000, "currency": "USD"},
        {"remote_required": True},
        {"seniority_in": ["senior", "staff"]},
    ]
    assert evaluate_many(preds, _candidate()) is True

    not_remote = _candidate(remote=False)
    assert evaluate_many(preds, not_remote) is False


def test_evaluate_many_empty_iterable_is_vacuously_true() -> None:
    assert evaluate_many([], _candidate()) is True


def test_evaluate_rejects_wrong_types() -> None:
    with pytest.raises(PredicateError):
        evaluate({"min_comp": "200000"}, _candidate())
    with pytest.raises(PredicateError):
        evaluate({"min_comp": True}, _candidate())
    with pytest.raises(PredicateError):
        evaluate({"location_any": "us"}, _candidate())
    with pytest.raises(PredicateError):
        evaluate({"currency": 1}, _candidate())
    with pytest.raises(PredicateError):
        evaluate({"currency": ""}, _candidate())
    with pytest.raises(PredicateError):
        evaluate({"remote_required": "yes"}, _candidate())


def test_string_list_clauses_handle_empty_and_bad_entries() -> None:
    assert evaluate({"location_any": []}, _candidate()) is True
    assert evaluate({"location_none": []}, _candidate()) is True
    assert evaluate({"title_keywords_any": []}, _candidate()) is True
    assert evaluate({"title_keywords_none": []}, _candidate()) is True
    assert evaluate({"location_any": ["  ", "remote"]}, _candidate()) is True
    with pytest.raises(PredicateError):
        evaluate({"location_any": [1]}, _candidate())
    with pytest.raises(PredicateError):
        evaluate({"seniority_in": []}, _candidate())


def test_clause_dispatch_defensive_unhandled_key() -> None:
    with pytest.raises(PredicateError):
        predicate._check_clause("bogus", None, _candidate())
