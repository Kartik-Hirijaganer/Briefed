"""Contract tests for the Phase 4 :class:`JobMatch` Pydantic schema.

Covers:

* happy path with full field set;
* text fields are trimmed and empty strings rejected;
* ``currency`` is normalized to upper-case ISO-4217;
* ``extra='forbid'`` catches hallucinated fields;
* JSON schema on disk stays in lockstep with the Pydantic mirror.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.llm.schemas import JobMatch

_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "packages" / "prompts" / "schemas"


def _load_schema(name: str) -> dict[str, object]:
    """Return the JSON schema for ``name`` (``schemas/<name>``)."""
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_job_match_happy_path() -> None:
    match = JobMatch(
        title="  Staff Backend Engineer  ",
        company="Acme",
        location="  US  ",
        remote=True,
        comp_min=210_000,
        comp_max=260_000,
        currency="usd",
        comp_phrase="$210k-$260k",
        seniority="staff",
        source_url="https://acme.example/jobs/staff-backend",
        match_reason="  Remote staff-level backend role.  ",
        confidence=0.92,
    )
    assert match.title == "Staff Backend Engineer"
    assert match.location == "US"
    assert match.currency == "USD"
    assert match.match_reason == "Remote staff-level backend role."


def test_job_match_normalizes_blank_optional_fields_to_none() -> None:
    match = JobMatch(
        title="Engineer",
        company="Beta",
        location="   ",
        comp_phrase="",
        source_url=" ",
        match_reason="Role details",
        confidence=0.7,
    )
    assert match.location is None
    assert match.comp_phrase is None
    assert match.source_url is None


def test_job_match_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        JobMatch.model_validate(
            {
                "title": "Engineer",
                "company": "Gamma",
                "match_reason": "x",
                "confidence": 0.8,
                "equity_percent": 0.5,
            },
        )


def test_job_match_rejects_blank_required_fields() -> None:
    with pytest.raises(ValidationError):
        JobMatch(
            title="   ",
            company="Acme",
            match_reason="Valid rationale",
            confidence=0.9,
        )
    with pytest.raises(ValidationError):
        JobMatch(
            title="Engineer",
            company="Acme",
            match_reason="   ",
            confidence=0.9,
        )


def test_job_match_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        JobMatch(
            title="Engineer",
            company="Acme",
            match_reason="x",
            confidence=1.3,
        )
    with pytest.raises(ValidationError):
        JobMatch(
            title="Engineer",
            company="Acme",
            match_reason="x",
            confidence=-0.1,
        )


def test_job_match_currency_must_be_three_letters() -> None:
    with pytest.raises(ValidationError):
        JobMatch(
            title="Engineer",
            company="Acme",
            match_reason="x",
            confidence=0.8,
            currency="US",
        )
    with pytest.raises(ValidationError):
        JobMatch(
            title="Engineer",
            company="Acme",
            match_reason="x",
            confidence=0.8,
            currency="US1",
        )


def test_job_match_seniority_enum() -> None:
    with pytest.raises(ValidationError):
        JobMatch(
            title="Engineer",
            company="Acme",
            match_reason="x",
            confidence=0.8,
            seniority="fellow",
        )


def test_json_schema_in_sync_with_pydantic() -> None:
    schema = _load_schema("job_extract.v1.json")
    assert schema["additionalProperties"] is False
    required = set(schema["required"])  # type: ignore[index]
    assert required == {"title", "company", "match_reason", "confidence"}
    assert set(schema["properties"]) == {  # type: ignore[index]
        "title",
        "company",
        "location",
        "remote",
        "comp_min",
        "comp_max",
        "currency",
        "comp_phrase",
        "seniority",
        "source_url",
        "match_reason",
        "confidence",
    }
