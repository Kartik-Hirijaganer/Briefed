"""Contract tests for Phase 3 summarization Pydantic schemas.

Ensures the JSON tool-use contract is enforced on both ends: the model
may only emit the declared fields (``extra='forbid'``), validator
constraints reject empty / oversized payloads, and the JSON Schema on
disk stays in lockstep with the Pydantic mirror.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.llm.schemas import EmailSummary, TechNewsClusterSummary

_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "packages" / "prompts" / "schemas"


def _load_schema(name: str) -> dict[str, object]:
    """Return the JSON schema for ``name`` (``schemas/<name>``)."""
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_email_summary_happy_path() -> None:
    summary = EmailSummary(
        tldr="  Direct coordination ask.  ",
        key_points=("Meeting at 10a", "", "Hiring loop"),
        action_items=("Confirm the call",),
        entities=("ACME",),
        confidence=0.9,
    )
    assert summary.tldr == "Direct coordination ask."
    assert summary.key_points == ("Meeting at 10a", "Hiring loop")
    assert summary.action_items == ("Confirm the call",)


def test_email_summary_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EmailSummary.model_validate(
            {
                "tldr": "Hello",
                "confidence": 0.9,
                "unexpected": True,
            },
        )


def test_email_summary_rejects_empty_tldr() -> None:
    with pytest.raises(ValidationError):
        EmailSummary(tldr="   ", confidence=0.5)


def test_email_summary_confidence_range() -> None:
    with pytest.raises(ValidationError):
        EmailSummary(tldr="x", confidence=1.5)


def test_email_summary_caps_list_length() -> None:
    with pytest.raises(ValidationError):
        EmailSummary(
            tldr="x",
            key_points=("a", "b", "c", "d", "e", "f"),
            confidence=0.9,
        )


def test_tech_news_cluster_summary_happy_path() -> None:
    cluster = TechNewsClusterSummary(
        cluster_key="  LLM-Research ",
        headline="  Open-weight releases  ",
        bullets=("Meta released Llama", "Mistral shipped MoE"),
        sources=("Open weights roundup", "Weekly ML digest"),
        confidence=0.88,
    )
    assert cluster.cluster_key == "llm-research"
    assert cluster.headline == "Open-weight releases"
    assert len(cluster.bullets) == 2


def test_tech_news_cluster_summary_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        TechNewsClusterSummary.model_validate(
            {
                "cluster_key": "ai",
                "headline": "x",
                "confidence": 0.5,
                "extra": True,
            },
        )


def test_json_schema_in_sync_with_pydantic_email_summary() -> None:
    schema = _load_schema("summarize_relevant.v1.json")
    required = set(schema["required"])  # type: ignore[index]
    assert required == {"tldr", "confidence"}
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {  # type: ignore[index]
        "tldr",
        "key_points",
        "action_items",
        "entities",
        "confidence",
    }


def test_json_schema_in_sync_with_pydantic_cluster_summary() -> None:
    schema = _load_schema("newsletter_group.v1.json")
    required = set(schema["required"])  # type: ignore[index]
    assert required == {"cluster_key", "headline", "confidence"}
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {  # type: ignore[index]
        "cluster_key",
        "headline",
        "bullets",
        "sources",
        "confidence",
    }
