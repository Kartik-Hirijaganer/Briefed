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
]
"""Primary triage-bucket enumeration mirrored from ``triage.v2.json``.

Newsletter detection is an independent boolean flag, not a primary bucket.
Low-confidence rows stay in one of these buckets and set
``Classification.needs_review`` for the UI badge.
"""

CategoryDigestCategory = Literal[
    "must_read",
    "good_to_read",
]
"""Categories that receive run-level digest rollups."""


class TriageDecision(BaseModel):
    """Structured output of the triage prompt (plan §6, §14 Phase 2).

    Attributes:
        category: Bucket assignment; one of :data:`TriageCategory`.
        confidence: Calibrated probability in ``[0, 1]``.
        reasons_short: One-sentence rationale; trimmed to 200 chars.
        is_newsletter: Convenience flag — subscribable bulk sender.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: TriageCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasons_short: str = Field(..., max_length=200)
    is_newsletter: bool = Field(default=False)

    @field_validator("reasons_short")
    @classmethod
    def _strip_whitespace(cls, value: str) -> str:
        """Trim surrounding whitespace; keep internal punctuation intact."""
        return value.strip()


class EmailSummary(BaseModel):
    """Per-email summary produced by ``summarize_relevant`` (plan §6, §14 Phase 3).

    Emitted by Gemini Flash (primary) or Claude Haiku 4.5 (fallback) via
    :class:`app.llm.client.LLMClient`. Written — envelope-encrypted — to
    ``summaries.body_md_ct`` + ``summaries.entities_ct`` by
    :class:`app.services.summarization.repository.SummariesRepo`.

    The model intentionally refuses extra fields so a hallucinated
    ``next_steps`` / ``sentiment`` key does not silently end up on disk;
    the value objects the UI reads are the ones declared here.

    Attributes:
        tldr: One-sentence summary (max 240 chars). Must be faithful to
            the source body — the eval rubric scores for this.
        key_points: Up to five bullet fragments lifted from the body.
        action_items: Up to three concrete asks or deadlines. May be
            empty when the email is purely informational.
        entities: Zero-or-more proper-noun mentions the UI can surface
            as chips (people, orgs, products). Each entry is 1-80 chars.
        confidence: Calibrated ``[0, 1]``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tldr: str = Field(..., min_length=1, max_length=240)
    key_points: tuple[str, ...] = Field(default=(), max_length=5)
    action_items: tuple[str, ...] = Field(default=(), max_length=3)
    entities: tuple[str, ...] = Field(default=(), max_length=20)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("tldr")
    @classmethod
    def _strip_tldr(cls, value: str) -> str:
        """Strip surrounding whitespace; reject empty strings."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("tldr must be non-empty")
        return stripped

    @field_validator("key_points", "action_items", "entities")
    @classmethod
    def _strip_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Drop empties and whitespace-only entries from the list."""
        return tuple(item.strip() for item in value if item and item.strip())


class CategoryDigestGroup(BaseModel):
    """One thematic group inside a category-level digest summary.

    Attributes:
        label: Short heading for the group.
        bullets: Factual bullets synthesized from source email summaries.
        item_refs: Opaque source item refs supplied in the prompt input.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(..., min_length=1, max_length=80, description="Short group heading.")
    bullets: tuple[str, ...] = Field(
        default=(),
        max_length=5,
        description="Factual bullets for this group.",
    )
    item_refs: tuple[str, ...] = Field(
        default=(),
        max_length=20,
        description="Opaque source refs cited by this group.",
    )

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        """Trim surrounding whitespace; reject empty labels."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("label must be non-empty")
        return stripped

    @field_validator("bullets", "item_refs")
    @classmethod
    def _strip_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Drop empty entries and trim surrounding whitespace."""
        return tuple(item.strip() for item in value if item and item.strip())


class CategoryDigestSummary(BaseModel):
    """Run-level synthesized summary for one triage category.

    Produced by ``category_digest/v1.md`` after a run's classifications
    and per-email summaries have fully drained. The input is the complete
    run/category set of per-email TL;DRs and key points.

    Attributes:
        narrative: Short prose rollup for the category.
        groups: Thematic source-backed groups.
        confidence: Calibrated ``[0, 1]``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative: str = Field(
        ...,
        min_length=1,
        max_length=800,
        description="Short prose rollup for the category.",
    )
    groups: tuple[CategoryDigestGroup, ...] = Field(
        default=(),
        max_length=8,
        description="Thematic source-backed groups.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence that the digest is faithful.",
    )

    @field_validator("narrative")
    @classmethod
    def _strip_narrative(cls, value: str) -> str:
        """Trim surrounding whitespace; reject empty narratives."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("narrative must be non-empty")
        return stripped


UnsubscribeCategory = Literal[
    "promotional",
    "newsletter",
    "notification",
    "social",
    "other",
]
"""Sender archetype enum mirrored from ``unsubscribe_borderline.v1.json``."""


class UnsubscribeDecision(BaseModel):
    """Structured output of the ``unsubscribe_borderline`` prompt (plan §14 Phase 5).

    Emitted by Gemini Flash (primary) or Claude Haiku 4.5 (fallback)
    via :class:`app.llm.client.LLMClient` on senders the SQL aggregate
    flagged as 2-of-3 borderline. Written — with ``rationale``
    envelope-encrypted — to
    :class:`app.db.models.UnsubscribeSuggestion` via
    :class:`app.services.unsubscribe.repository.UnsubscribeSuggestionsRepo`.

    The model refuses extra fields so a hallucinated ``action_url`` /
    ``sender_is_spam`` key cannot leak onto disk; the value objects
    the UI renders are the ones declared here.

    Attributes:
        should_recommend: Final verdict; ``True`` when the sender
            should appear on the unsubscribe board.
        confidence: Calibrated ``[0, 1]``. The prompt caps this at
            0.95; values at or below 0.8 never auto-act.
        category: Sender archetype (``promotional`` / ``newsletter``
            / ``notification`` / ``social`` / ``other``).
        rationale: One-sentence explanation citing the aggregate
            signals. Encrypted at rest. Trimmed to 240 characters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    should_recommend: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    category: UnsubscribeCategory
    rationale: str = Field(..., min_length=1, max_length=240)

    @field_validator("rationale")
    @classmethod
    def _strip_rationale(cls, value: str) -> str:
        """Trim surrounding whitespace; reject empty rationales."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("rationale must be non-empty")
        return stripped


class TechNewsClusterSummary(BaseModel):
    """Group summary for one newsletter cluster (plan §14 Phase 3).

    Produced by ``newsletter_group/v1.md`` when a run has ≥ 2 emails
    routed to the same cluster (``cluster_hint`` from
    ``known_newsletters`` or a deterministic domain-based bucket).

    Attributes:
        cluster_key: Stable slug identifying the cluster (e.g.
            ``llm-research`` / ``aws-weekly``). Plumbed through to the UI
            filter bar.
        headline: Short cluster caption (max 120 chars).
        bullets: Up to six cross-story bullets. Each string is lifted /
            paraphrased from the underlying emails; no speculation.
        sources: Subjects of the underlying newsletters in source order.
            The UI uses this to render source attribution chips.
        confidence: Calibrated ``[0, 1]``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cluster_key: str = Field(..., min_length=1, max_length=64)
    headline: str = Field(..., min_length=1, max_length=120)
    bullets: tuple[str, ...] = Field(default=(), max_length=6)
    sources: tuple[str, ...] = Field(default=(), max_length=20)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("cluster_key")
    @classmethod
    def _slug(cls, value: str) -> str:
        """Normalize cluster keys to lowercase slugs — stable across runs."""
        slug = value.strip().lower()
        if not slug:
            raise ValueError("cluster_key must be non-empty")
        return slug

    @field_validator("headline")
    @classmethod
    def _strip_headline(cls, value: str) -> str:
        """Trim surrounding whitespace; keep interior punctuation."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("headline must be non-empty")
        return stripped

    @field_validator("bullets", "sources")
    @classmethod
    def _strip_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Drop empties + whitespace-only entries."""
        return tuple(item.strip() for item in value if item and item.strip())


__all__ = [
    "CategoryDigestCategory",
    "CategoryDigestGroup",
    "CategoryDigestSummary",
    "EmailSummary",
    "TechNewsClusterSummary",
    "TriageCategory",
    "TriageDecision",
    "UnsubscribeCategory",
    "UnsubscribeDecision",
]
