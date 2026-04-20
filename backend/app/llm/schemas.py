"""Pydantic tool-use schemas for LLM calls (plan §6).

Every structured output produced by an LLM crosses one of these classes
before landing on disk. ``ConfigDict(frozen=True, extra="forbid")`` so a
model hallucinating an extra field raises :class:`ValidationError` at
the ingestion boundary instead of silently writing garbage.

The authoritative JSON Schemas live under
``packages/prompts/schemas/*.json``; these Pydantic models are the
runtime mirror.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TriageCategory = Literal[
    "must_read",
    "good_to_read",
    "ignore",
    "waste",
    "newsletter",
    "job_candidate",
    "needs_review",
]
"""Bucket enumeration mirrored from ``triage.v1.json``."""


class TriageDecision(BaseModel):
    """Structured output of the triage prompt (plan §6, §14 Phase 2).

    Attributes:
        category: Bucket assignment; one of :data:`TriageCategory`.
        confidence: Calibrated probability in ``[0, 1]``.
        reasons_short: One-sentence rationale; trimmed to 200 chars.
        is_newsletter: Convenience flag — subscribable bulk sender.
        is_job_candidate: Convenience flag — recruiter / job reach-out.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: TriageCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasons_short: str = Field(..., max_length=200)
    is_newsletter: bool = Field(default=False)
    is_job_candidate: bool = Field(default=False)

    @field_validator("reasons_short")
    @classmethod
    def _strip_whitespace(cls, value: str) -> str:
        """Trim surrounding whitespace; keep internal punctuation intact."""
        return value.strip()


__all__ = ["TriageCategory", "TriageDecision"]
