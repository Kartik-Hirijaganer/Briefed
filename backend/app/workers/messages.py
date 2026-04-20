"""Pydantic payloads for SQS messages (plan §14 Phase 1 + Phase 2).

Every queue carries a discriminated-union payload. Phase 1 shipped
:class:`IngestMessage`; Phase 2 adds :class:`ClassifyMessage`. Later
phases add ``SummarizeMessage``, ``JobExtractMessage`` etc.
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
