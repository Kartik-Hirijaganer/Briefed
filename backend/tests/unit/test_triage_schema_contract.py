"""Contract test: the authoritative JSON schema + Pydantic model agree.

Phase 2 exit criterion: "tool-use JSON ``extra='forbid'`` rejects extra
fields." This module confirms
``packages/prompts/schemas/triage.v1.json`` stays in lock-step with
:class:`app.llm.schemas.TriageDecision`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.llm.schemas import TriageDecision

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "packages" / "prompts" / "schemas" / "triage.v1.json"
)


def test_schema_is_additional_properties_false() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False


def test_schema_required_mirrors_model_required() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema["required"]) == {"category", "confidence", "reasons_short"}


def test_schema_categories_match_pydantic_literal() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_categories = set(schema["properties"]["category"]["enum"])
    pydantic_categories = set(get_args(TriageDecision.model_fields["category"].annotation))
    assert schema_categories == pydantic_categories


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        TriageDecision.model_validate(
            {
                "category": "must_read",
                "confidence": 0.9,
                "reasons_short": "ok",
                "unexpected": True,
            },
        )
