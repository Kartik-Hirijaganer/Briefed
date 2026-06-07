"""Pydantic boundary models for the unsubscribe + hygiene API (plan §14 Phase 5).

Three API surfaces share this module:

* ``GET /api/v1/unsubscribes`` — top-N unsubscribe recommendations for
  the caller, highest confidence first, with ``dismissed`` rows hidden
  by default.
* ``POST /api/v1/unsubscribes/{id}/dismiss`` — mark a row as dismissed
  (records ``dismissed_at``). The aggregate preserves this across
  re-runs (plan §14 Phase 5 exit criteria: "dismiss survives reload").
* ``POST /api/v1/unsubscribes/{id}/confirm`` — record that the user
  clicked through and acted on the recommendation. Release 1.0.0 is
  **recommend-only** (ADR 0006) so this does not touch Gmail; it
  simply flips ``dismissed=True`` with a ``confirmed_at`` audit note
  in the logs.

The ``GET /api/v1/hygiene/stats`` endpoint returns a small aggregate
over the same table — total candidates, dismissed count, average
frequency, and the top sender domains by email volume.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UnsubscribeActionOut(BaseModel):
    """Normalized ``List-Unsubscribe`` target surfaced to the UI.

    Attributes:
        http_urls: Every HTTP/HTTPS URL advertised by the sender.
        mailto: First ``mailto:`` URI, if present.
        one_click: RFC 8058 one-click POST is supported.
    """

    model_config = ConfigDict(frozen=True)

    http_urls: tuple[str, ...] = Field(default=())
    mailto: str | None = Field(default=None)
    one_click: bool = Field(default=False)


class UnsubscribeSuggestionOut(BaseModel):
    """Response row for ``GET /unsubscribes``.

    Attributes:
        id: Suggestion primary key.
        sender_domain: Normalized sender domain.
        sender_email: Full normalized address.
        frequency_30d: Emails received in the trailing 30 days.
        engagement_score: Positive-label ratio, 3-decimal precision.
        waste_rate: Waste/ignore ratio, 3-decimal precision.
        confidence: Calibrated ``[0, 1]`` — the UI hides rows below
            ``0.5`` by default.
        decision_source: ``rule`` or ``model``.
        category: Sender archetype when the model decided; ``None`` for
            rule-only rows (the UI can still render a heuristic badge).
        rationale: Plaintext rationale (decrypted by the router).
        list_unsubscribe: Normalized action payload. ``None`` when no
            email from this sender in the window carried a
            ``List-Unsubscribe`` header.
        dismissed: User-side dismissal flag.
        dismissed_at: When the user dismissed (``None`` while active).
        last_email_at: Most recent email time from this sender.
        created_at: First-insert timestamp of the suggestion row.
        updated_at: Last aggregate-update timestamp.
        recent_subjects: Up to six newest-first plaintext subject lines
            from this sender (already truncated by the aggregator). Empty
            when the row predates the column or no subjects were captured.
            Read-only — the UI shows them as recent-activity chips.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    sender_domain: str
    sender_email: str
    frequency_30d: int
    engagement_score: Decimal
    waste_rate: Decimal
    confidence: Decimal
    decision_source: Literal["rule", "model"]
    category: str | None
    rationale: str
    list_unsubscribe: UnsubscribeActionOut | None
    dismissed: bool
    dismissed_at: datetime | None
    last_email_at: datetime | None
    created_at: datetime
    updated_at: datetime
    recent_subjects: tuple[str, ...] = Field(
        default=(),
        description="Up to six newest-first plaintext recent subject lines.",
    )


class UnsubscribeExecuteRequest(BaseModel):
    """Body for ``POST /unsubscribes/{id}/execute`` (ADR 0014).

    The explicit ``confirm`` flag is the per-action confirmation gate ADR 0014
    requires — the endpoint rejects a request without it.

    Attributes:
        confirm: Must be ``True`` to execute; the frontend sets it only after
            the user confirms the destructive action.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirm: bool = Field(
        ...,
        description="Explicit per-action confirmation; must be true to execute.",
    )


class UnsubscribeExecuteResponse(BaseModel):
    """Result of an execute attempt (ADR 0014).

    Attributes:
        status: ``unsubscribed`` (one-click POST succeeded), ``manual_required``
            (the user must open :attr:`manual_url` to finish), or ``failed``.
        executed_via: ``one_click`` when Briefed sent the request, else
            ``none``.
        manual_url: URL/``mailto:`` to open for ``manual_required``; ``None``
            otherwise.
        message: Human-readable summary for the UI.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["unsubscribed", "manual_required", "failed"] = Field(
        ...,
        description="Execute lifecycle outcome.",
    )
    executed_via: Literal["one_click", "none"] = Field(
        ...,
        description="How the unsubscribe was performed.",
    )
    manual_url: str | None = Field(
        default=None,
        description="URL the user must open when a manual step is required.",
    )
    message: str = Field(..., description="Human-readable outcome summary.")


class UnsubscribeSuggestionsListResponse(BaseModel):
    """Envelope for ``GET /unsubscribes``.

    Attributes:
        suggestions: Highest-confidence-first list of suggestion rows
            the caller is allowed to see.
    """

    model_config = ConfigDict(frozen=True)

    suggestions: tuple[UnsubscribeSuggestionOut, ...] = Field(default=())


class DomainWasteEntry(BaseModel):
    """One row in the hygiene-stats top-senders table.

    Attributes:
        sender_domain: Normalized domain.
        frequency_30d: Sum of emails across all sender_emails in this
            domain.
        waste_share: Fraction ``waste_30d / frequency_30d`` for the
            domain (0 when the domain has no classified waste rows).
    """

    model_config = ConfigDict(frozen=True)

    sender_domain: str
    frequency_30d: int
    waste_share: Decimal


class HygieneStatsResponse(BaseModel):
    """Envelope for ``GET /hygiene/stats``.

    Attributes:
        total_candidates: Count of active (``dismissed=False``)
            suggestion rows.
        dismissed_count: Count of rows the user has dismissed.
        average_frequency: Mean ``frequency_30d`` over active
            suggestions. ``0`` when there are none.
        top_domains: Up to ten highest-volume sender domains in the
            30-day window, by summed frequency.
    """

    model_config = ConfigDict(frozen=True)

    total_candidates: int
    dismissed_count: int
    average_frequency: Decimal
    top_domains: tuple[DomainWasteEntry, ...] = Field(default=())


__all__ = [
    "DomainWasteEntry",
    "HygieneStatsResponse",
    "UnsubscribeActionOut",
    "UnsubscribeExecuteRequest",
    "UnsubscribeExecuteResponse",
    "UnsubscribeSuggestionOut",
    "UnsubscribeSuggestionsListResponse",
]
