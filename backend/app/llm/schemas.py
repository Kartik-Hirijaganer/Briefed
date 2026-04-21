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
    "needs_review",
]
"""Primary triage-bucket enumeration mirrored from ``triage.v1.json``.

Newsletter and job-candidate detection are independent boolean flags, not
primary buckets. Downstream routing fans out from those flags while the
four-way attention label stays stable.
"""


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
        confidence: Calibrated ``[0, 1]`` — values below 0.55 route the
            row to ``needs_review`` in the pipeline policy gate.
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


class JobMatch(BaseModel):
    """Structured extraction of a job posting (plan §6, §14 Phase 4).

    Emitted by ``job_extract/v1.md``. Written — with ``match_reason``
    envelope-encrypted — to the ``job_matches`` table via
    :class:`app.services.jobs.repository.JobMatchesRepo`.

    The model refuses extra fields so a hallucinated ``equity`` or
    ``work_hours`` key cannot slip onto disk. Every numeric salary is
    required to cite a verbatim ``comp_phrase`` lifted from the body;
    :func:`app.services.jobs.extractor.corroborate_comp` rejects rows
    whose phrase does not re-match the source body with a conservative
    regex.

    Attributes:
        title: Role title (e.g. "Senior Backend Engineer"). Required.
        company: Hiring company / recruiting firm. Required.
        location: Free-text location (city / region / country / empty).
            ``None`` when absent — never an inferred default like
            "Remote".
        remote: Tri-state — ``True`` when the post explicitly says
            remote is offered, ``False`` when it explicitly says on-site
            only, ``None`` when the post is ambiguous.
        comp_min: Inclusive lower bound of the compensation range, in
            :attr:`currency` units. Omitted if the post does not state a
            numeric range (we never infer from market rates).
        comp_max: Inclusive upper bound of the compensation range.
        currency: ISO-4217 currency code matching :attr:`comp_min` /
            :attr:`comp_max`. Required when either bound is set.
        comp_phrase: Verbatim text the LLM copied the salary from
            (e.g. "$150k-$210k"). Powers the regex corroboration guard.
        seniority: Optional seniority tier — one of the enum values to
            keep filter predicates portable.
        source_url: Apply / posting URL the recipient should open.
            ``None`` if the email did not include one.
        match_reason: One-paragraph fit rationale. Encrypted at rest.
        confidence: Calibrated ``[0, 1]``. Values below 0.7 suppress
            ``passed_filter=True`` (plan §14 Phase 4 exit criteria).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(..., min_length=1, max_length=200)
    company: str = Field(..., min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    remote: bool | None = Field(default=None)
    comp_min: int | None = Field(default=None, ge=0, le=10_000_000)
    comp_max: int | None = Field(default=None, ge=0, le=10_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    comp_phrase: str | None = Field(default=None, max_length=200)
    seniority: (
        Literal[
            "intern",
            "junior",
            "mid",
            "senior",
            "staff",
            "principal",
            "director",
            "executive",
        ]
        | None
    ) = Field(default=None)
    source_url: str | None = Field(default=None, max_length=2048)
    match_reason: str = Field(..., min_length=1, max_length=600)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("title", "company", "match_reason")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        """Strip whitespace; reject empty strings after trimming."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("required text field must be non-empty")
        return stripped

    @field_validator("location", "comp_phrase", "source_url")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        """Trim whitespace; turn all-whitespace strings into ``None``."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("currency")
    @classmethod
    def _uppercase_currency(cls, value: str | None) -> str | None:
        """Normalize ISO-4217 codes to uppercase."""
        if value is None:
            return None
        stripped = value.strip().upper()
        if not stripped:
            return None
        if len(stripped) != 3 or not stripped.isalpha():
            raise ValueError("currency must be a 3-letter ISO-4217 code")
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
    "EmailSummary",
    "JobMatch",
    "TechNewsClusterSummary",
    "TriageCategory",
    "TriageDecision",
    "UnsubscribeCategory",
    "UnsubscribeDecision",
]
