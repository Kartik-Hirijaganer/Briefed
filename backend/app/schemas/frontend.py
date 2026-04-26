"""Pydantic models for the Phase 6 PWA/dashboard API surface.

These models back the frontend-only read models that cut across several
pipeline tables: preferences, manual-run state, triage lists, daily digest,
and tech-news clusters. The worker still owns the durable pipeline writes;
these DTOs shape the HTTP contract consumed by the React PWA.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.emails import EmailRowOut


class UserPreferencesOut(BaseModel):
    """Current user's global PWA preferences.

    Attributes:
        auto_execution_enabled: Global scheduled-scan switch.
        digest_send_hour_utc: Hour of day for the daily digest.
        redact_pii: Whether prompt input redaction is enabled.
        secure_offline_mode: Whether the PWA should encrypt local offline
            data with a passcode.
        retention_policy_json: Operator-readable retention knobs.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    auto_execution_enabled: bool
    digest_send_hour_utc: int = Field(ge=0, le=23)
    redact_pii: bool
    secure_offline_mode: bool
    retention_policy_json: dict[str, Any]


class PreferencesPatchRequest(BaseModel):
    """Partial update body for ``PATCH /preferences``.

    Attributes mirror :class:`UserPreferencesOut`; omitted fields keep
    their current value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    auto_execution_enabled: bool | None = Field(default=None)
    digest_send_hour_utc: int | None = Field(default=None, ge=0, le=23)
    redact_pii: bool | None = Field(default=None)
    secure_offline_mode: bool | None = Field(default=None)
    retention_policy_json: dict[str, Any] | None = Field(default=None)


class ManualRunRequest(BaseModel):
    """Request body for ``POST /runs``.

    Attributes:
        kind: Only ``manual`` is supported by the HTTP trigger.
        account_ids: Optional subset of connected accounts to scan.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["manual"] = "manual"
    account_ids: tuple[UUID, ...] | None = Field(default=None)


class ManualRunResponse(BaseModel):
    """Accepted manual-run response.

    Attributes:
        run_id: New ``digest_runs.id`` for polling/history.
        accounts_queued: Number of owned accounts included in the run.
    """

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    accounts_queued: int = Field(ge=0)


class RunStats(BaseModel):
    """Compact run counters shown by history and progress polling."""

    model_config = ConfigDict(frozen=True)

    ingested: int = Field(default=0, ge=0)
    classified: int = Field(default=0, ge=0)
    summarized: int = Field(default=0, ge=0)
    new_must_read: int = Field(default=0, ge=0)


class RunStatusResponse(BaseModel):
    """Digest-run row returned by ``GET /runs/{id}`` and history.

    Attributes:
        id: Run primary key.
        status: Queue/progress state.
        trigger_type: Scheduled or user-triggered.
        started_at: Run start timestamp.
        completed_at: Completion timestamp, if finished.
        stats: Compact stage counters.
        cost_cents: Rounded LLM spend, if known.
        error: User-safe failure summary, if failed.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    status: Literal["queued", "running", "complete", "failed"]
    trigger_type: Literal["scheduled", "manual"]
    started_at: datetime
    completed_at: datetime | None = Field(default=None)
    stats: RunStats = Field(default_factory=RunStats)
    cost_cents: int | None = Field(default=None, ge=0)
    error: str | None = Field(default=None)


class RunsListResponse(BaseModel):
    """Envelope for ``GET /history``.

    Attributes:
        runs: Newest-first list of digest runs.
    """

    model_config = ConfigDict(frozen=True)

    runs: tuple[RunStatusResponse, ...] = Field(default=())


class DigestCounts(BaseModel):
    """Daily digest triage counts."""

    model_config = ConfigDict(frozen=True)

    must_read: int = Field(default=0, ge=0)
    good_to_read: int = Field(default=0, ge=0)
    ignore: int = Field(default=0, ge=0)
    waste: int = Field(default=0, ge=0)


class DigestTodayResponse(BaseModel):
    """Dashboard summary for the current daily digest.

    Attributes:
        generated_at: Timestamp of the latest successful run.
        cost_cents_today: Rounded prompt spend for today.
        counts: Current triage counts.
        must_read_preview: Newest must-read rows.
        last_successful_run_at: Timestamp used for freshness warnings.
    """

    model_config = ConfigDict(frozen=True)

    generated_at: datetime | None = Field(default=None)
    cost_cents_today: int = Field(ge=0)
    counts: DigestCounts
    must_read_preview: tuple[EmailRowOut, ...] = Field(default=())
    last_successful_run_at: datetime | None = Field(default=None)


class NewsCluster(BaseModel):
    """Tech-news cluster shown on ``/news``.

    Attributes:
        id: Cluster primary key.
        label: Human-readable topic label.
        summary_md: Plaintext markdown summary.
        email_ids: Source email ids in the cluster.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    label: str
    summary_md: str
    email_ids: tuple[UUID, ...] = Field(default=())


class NewsDigestResponse(BaseModel):
    """Envelope for ``GET /news``."""

    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    clusters: tuple[NewsCluster, ...] = Field(default=())


__all__ = [
    "DigestCounts",
    "DigestTodayResponse",
    "ManualRunRequest",
    "ManualRunResponse",
    "NewsCluster",
    "NewsDigestResponse",
    "PreferencesPatchRequest",
    "RunStats",
    "RunStatusResponse",
    "RunsListResponse",
    "UserPreferencesOut",
]
