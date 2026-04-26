"""Pydantic boundary models for the jobs + job-filters API (plan §14 Phase 4).

Two API surfaces share this module:

* ``/api/v1/jobs`` — read-only listing of :class:`app.db.models.JobMatch`
  rows, with optional ``passed_filter`` filtering for the curated board.
* ``/api/v1/job-filters`` — CRUD over :class:`app.db.models.JobFilter`
  rows. Each mutation bumps :attr:`JobFilter.version` so the next
  job-extract worker run stamps the new version onto downstream
  :attr:`JobMatch.filter_version` writes.

The predicate body is validated at the request boundary by the same
:class:`app.services.jobs.predicate` whitelist the worker uses; the
router refuses unknown keys before the row is persisted so a typo
cannot widen a filter at runtime.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.jobs.predicate import JobCandidate as _JobCandidate
from app.services.jobs.predicate import PredicateError, evaluate


class JobFilterIn(BaseModel):
    """Request body for ``POST /job-filters`` and ``PUT /job-filters/{id}``.

    Attributes:
        name: Human-readable label, unique per user (DB enforces).
        predicate: JSONB document consumed by
            :func:`app.services.jobs.predicate.evaluate`.
        active: Soft-delete switch. Defaults to ``True``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    predicate: dict[str, Any] = Field(..., min_length=1)
    active: bool = Field(default=True)

    @field_validator("predicate")
    @classmethod
    def _validate_predicate(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Reject unknown predicate keys and malformed clause shapes.

        Runs the same predicate against an inert :class:`JobCandidate`
        sentinel so every clause exercises its parser. A passing or
        failing evaluation is fine — what we care about is whether the
        clause shape parses; a :class:`PredicateError` is bubbled up as
        ``ValueError`` so FastAPI surfaces a 422.
        """
        sentinel = _JobCandidate(
            title="",
            company="",
            location=None,
            remote=None,
            comp_min=None,
            comp_max=None,
            currency=None,
            seniority=None,
            match_score=0.0,
        )
        try:
            evaluate(value, sentinel)
        except PredicateError as exc:
            raise ValueError(str(exc)) from exc
        return value


class JobFilterOut(BaseModel):
    """Response body for any ``/job-filters`` endpoint.

    Attributes:
        id: Filter primary key.
        name: Label.
        predicate: JSONB document.
        version: Bumped on every PUT.
        active: Soft-delete switch.
        created_at: First-insert timestamp.
        updated_at: Last-modified timestamp.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    name: str
    predicate: dict[str, Any]
    version: int
    active: bool
    created_at: datetime
    updated_at: datetime


class JobFiltersListResponse(BaseModel):
    """Envelope for ``GET /job-filters``.

    Attributes:
        filters: Every :class:`JobFilterOut` owned by the caller,
            ordered by ``created_at ASC`` so client-side ordering is
            stable across requests.
    """

    model_config = ConfigDict(frozen=True)

    filters: tuple[JobFilterOut, ...] = Field(default=())


class JobMatchOut(BaseModel):
    """Response row for ``GET /jobs``.

    Attributes:
        id: Match primary key.
        email_id: Source email FK.
        title: Role title.
        company: Hiring company / firm.
        location: Free-text location, ``None`` when the posting omitted it.
        remote: Tri-state remote flag.
        comp_min: Lower compensation bound.
        comp_max: Upper compensation bound.
        currency: ISO-4217 code.
        seniority: Normalized tier string.
        source_url: Apply / posting URL with tracking params stripped.
        match_score: Calibrated confidence, three-decimal precision.
        filter_version: Active-filter version snapshot at extract time.
        passed_filter: ``True`` when the row cleared every active filter
            and the confidence floor; the curated board surfaces only
            these.
        match_reason: Plaintext rationale (decrypted by the router).
        created_at: When the match row was first written.
        updated_at: When it was last replaced (re-extraction).
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    email_id: UUID
    title: str
    company: str
    location: str | None
    remote: bool | None
    comp_min: int | None
    comp_max: int | None
    currency: str | None
    seniority: str | None
    source_url: str | None
    match_score: Decimal
    filter_version: int
    passed_filter: bool
    match_reason: str
    created_at: datetime
    updated_at: datetime


class JobMatchesListResponse(BaseModel):
    """Envelope for ``GET /jobs``.

    Attributes:
        matches: Newest-first list of :class:`JobMatchOut` rows the
            caller is allowed to see.
    """

    model_config = ConfigDict(frozen=True)

    matches: tuple[JobMatchOut, ...] = Field(default=())


__all__ = [
    "JobFilterIn",
    "JobFilterOut",
    "JobFiltersListResponse",
    "JobMatchOut",
    "JobMatchesListResponse",
]
