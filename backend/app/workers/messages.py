"""Pydantic payloads for SQS messages (plan §14 Phase 1 through Phase 4).

Every queue carries a discriminated-union payload. Phase 1 shipped
:class:`IngestMessage`; Phase 2 added :class:`ClassifyMessage`; Phase 3
added :class:`SummarizeEmailMessage` and :class:`TechNewsClusterMessage`;
Phase 4 adds :class:`JobExtractMessage`. Later phases add
``UnsubscribeMessage`` etc.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IngestMessage(BaseModel):
    """SQS payload for the ``briefed-*-ingest`` queue.

    Attributes:
        kind: Discriminator literal. Always ``"ingest"`` on this queue.
        user_id: Owning user.
        account_id: Target connected account.
        run_id: Digest-run id this ingestion belongs to.
        store_raw_mime: Whether to persist MIME to S3 (owner toggle).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["ingest"] = "ingest"
    user_id: UUID
    account_id: UUID
    run_id: UUID | None = Field(default=None)
    store_raw_mime: bool = Field(default=False)


class ClassifyMessage(BaseModel):
    """SQS payload for the ``briefed-*-classify`` queue (plan §14 Phase 2).

    One message per email to be triaged. Workers fetch the email row +
    owning user, run :func:`app.services.classification.pipeline.classify_one`,
    and persist a ``classifications`` row.

    Attributes:
        kind: Discriminator literal. Always ``"classify"`` on this queue.
        user_id: Owning user — bound into the encryption context.
        account_id: Connected account the email belongs to.
        email_id: Target email.
        run_id: Optional digest-run this classification belongs to.
        prompt_name: Prompt key to use; defaults to ``"triage"``.
        prompt_version: Version; defaults to ``1``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["classify"] = "classify"
    user_id: UUID
    account_id: UUID
    email_id: UUID
    run_id: UUID | None = Field(default=None)
    prompt_name: str = Field(default="triage")
    prompt_version: int = Field(default=1, ge=1)


class SummarizeEmailMessage(BaseModel):
    """SQS payload for the ``briefed-*-summarize`` queue (plan §14 Phase 3).

    One message per email to be summarized. Workers fetch the email row,
    render the ``summarize_relevant`` prompt, and write a ``summaries``
    row keyed by ``email_id``.

    Attributes:
        kind: Discriminator literal. Always ``"summarize_email"``.
        user_id: Owning user — bound into the encryption context.
        account_id: Connected account the email belongs to.
        email_id: Target email.
        run_id: Optional digest-run scope.
        prompt_name: Prompt key; defaults to ``"summarize_relevant"``.
        prompt_version: Version; defaults to ``1``.
        batch_id: Optional Batch API job id when this message is
            replaying a previously-submitted batch.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["summarize_email"] = "summarize_email"
    user_id: UUID
    account_id: UUID
    email_id: UUID
    run_id: UUID | None = Field(default=None)
    prompt_name: str = Field(default="summarize_relevant")
    prompt_version: int = Field(default=1, ge=1)
    batch_id: str | None = Field(default=None)


class TechNewsClusterMessage(BaseModel):
    """SQS payload for the ``briefed-*-summarize`` queue — cluster variant.

    One message per run covering all newsletter emails for a user.
    Workers compute clusters, then run one LLM call per cluster via
    :func:`app.services.summarization.tech_news.cluster_and_summarize`.

    Attributes:
        kind: Discriminator literal. Always ``"tech_news_cluster"``.
        user_id: Owning user.
        run_id: Digest-run scope.
        email_ids: Newsletter email ids to cluster. Bounded by the
            fan-out so one message fits well inside SQS's 256 KB limit.
        prompt_name: Prompt key; defaults to ``"newsletter_group"``.
        prompt_version: Version; defaults to ``1``.
        min_cluster_size: Inclusive lower bound (default 2).
        max_cluster_size: Inclusive upper bound (default 8).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["tech_news_cluster"] = "tech_news_cluster"
    user_id: UUID
    run_id: UUID | None = Field(default=None)
    email_ids: tuple[UUID, ...]
    prompt_name: str = Field(default="newsletter_group")
    prompt_version: int = Field(default=1, ge=1)
    min_cluster_size: int = Field(default=2, ge=1, le=50)
    max_cluster_size: int = Field(default=8, ge=1, le=50)


class JobExtractMessage(BaseModel):
    """SQS payload for the ``briefed-*-jobs`` queue (plan §14 Phase 4).

    One message per ``job_candidate`` email. Workers fetch the email
    row, render the ``job_extract`` prompt, corroborate the salary
    against the body, evaluate every active ``job_filters`` predicate,
    and write a :class:`app.db.models.JobMatch` row keyed by ``email_id``.

    Attributes:
        kind: Discriminator literal. Always ``"job_extract"``.
        user_id: Owning user — bound into the encryption context.
        account_id: Connected account the email belongs to.
        email_id: Target email.
        run_id: Optional digest-run scope.
        prompt_name: Prompt key; defaults to ``"job_extract"``.
        prompt_version: Version; defaults to ``1``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["job_extract"] = "job_extract"
    user_id: UUID
    account_id: UUID
    email_id: UUID
    run_id: UUID | None = Field(default=None)
    prompt_name: str = Field(default="job_extract")
    prompt_version: int = Field(default=1, ge=1)


class FanoutMessage(BaseModel):
    """Envelope produced by EventBridge Scheduler → fan-out Lambda.

    Attributes:
        kind: Discriminator literal. Always ``"fanout"``.
        scheduled_at: UTC timestamp of the scheduler firing.
        user_id: Optional filter — when set, the fan-out enqueues only
            this user's accounts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["fanout"] = "fanout"
    scheduled_at: str
    user_id: UUID | None = Field(default=None)


__all__ = [
    "ClassifyMessage",
    "FanoutMessage",
    "IngestMessage",
    "JobExtractMessage",
    "SummarizeEmailMessage",
    "TechNewsClusterMessage",
]
