"""Pydantic payloads for SQS messages (plan §14 Phase 1).

Every queue carries a discriminated-union payload. Phase 1 ships one
shape: :class:`IngestMessage`. Subsequent phases add `ClassifyMessage`,
`SummarizeMessage`, etc.
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
