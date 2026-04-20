"""Unit tests for :func:`app.services.jobs.extractor.corroborate_comp`.

The corroboration guard is the plan §14 Phase 4 answer to the
"hallucinated salary" risk: rows whose ``comp_phrase`` does not
re-appear in the source body get their comp fields zeroed out and
their confidence capped below the digest floor.
"""

from __future__ import annotations

from app.llm.schemas import JobMatch
from app.services.jobs.extractor import corroborate_comp


def _match(**overrides: object) -> JobMatch:
    base: dict[str, object] = {
        "title": "Staff Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "remote": True,
        "comp_min": 210_000,
        "comp_max": 260_000,
        "currency": "USD",
        "comp_phrase": "$210k-$260k",
        "seniority": "staff",
        "source_url": "https://example.com/apply",
        "match_reason": "fits",
        "confidence": 0.9,
    }
    base.update(overrides)
    return JobMatch(**base)  # type: ignore[arg-type]


def test_corroboration_accepts_phrase_present_in_body() -> None:
    body = "Comp is $210k-$260k plus equity."
    out, ok = corroborate_comp(_match(), body=body)
    assert ok is True
    assert out.comp_min == 210_000
    assert out.comp_max == 260_000
    assert out.confidence == 0.9


def test_corroboration_accepts_normalized_whitespace() -> None:
    # LLM can normalize "$210,000 - $260,000" (en-dash + spaces) vs
    # body "$210,000-$260,000" — we only require the digit runs to line
    # up after stripping commas.
    body = "Range $210,000-$260,000 OTE."
    out, ok = corroborate_comp(
        _match(
            comp_phrase="$210,000 - $260,000",
            comp_min=210_000,
            comp_max=260_000,
        ),
        body=body,
    )
    assert ok is True
    assert out.comp_min == 210_000


def test_corroboration_sanitizes_when_phrase_missing_in_body() -> None:
    body = "Comp is negotiable."
    out, ok = corroborate_comp(_match(), body=body)
    assert ok is False
    assert out.comp_min is None
    assert out.comp_max is None
    assert out.currency is None
    assert out.comp_phrase is None
    # Confidence knocked below the digest floor so the row cannot ship.
    assert out.confidence < 0.7


def test_corroboration_sanitizes_when_phrase_is_none_but_numbers_present() -> None:
    # Defensive: model returned comp_min without comp_phrase — treat as
    # unsupported and strip.
    body = "Body without any numbers."
    out, ok = corroborate_comp(_match(comp_phrase=None), body=body)
    assert ok is False
    assert out.comp_min is None


def test_corroboration_noop_when_no_comp_returned() -> None:
    candidate = _match(
        comp_min=None,
        comp_max=None,
        currency=None,
        comp_phrase=None,
    )
    body = "No salary mentioned."
    out, ok = corroborate_comp(candidate, body=body)
    assert ok is True
    assert out is candidate


def test_corroboration_ignores_comp_phrase_without_digits() -> None:
    # "Competitive" isn't a number — no numeric claim to corroborate.
    candidate = _match(
        comp_min=None,
        comp_max=None,
        currency=None,
        comp_phrase="Competitive",
    )
    body = "We offer competitive compensation."
    out, ok = corroborate_comp(candidate, body=body)
    assert ok is True
    assert out.comp_phrase == "Competitive"


def test_corroboration_rejects_fabricated_numbers() -> None:
    # Body says $180k, model hallucinated $210k-$260k — reject.
    body = "Base $180,000 plus equity."
    out, ok = corroborate_comp(_match(), body=body)
    assert ok is False
    assert out.comp_min is None
