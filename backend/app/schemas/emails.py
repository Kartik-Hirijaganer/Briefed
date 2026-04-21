"""Pydantic boundary models for email list and bucket-update APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

EmailBucket = Literal["must_read", "good_to_read", "ignore", "waste"]
"""Primary triage bucket exposed to the PWA."""

DecisionSource = Literal["rule", "llm", "hybrid"]
"""Frontend decision-source vocabulary."""


class EmailRowOut(BaseModel):
    """Single row shown in dashboard and bucket lists.

    Attributes:
        id: Email primary key.
        account_email: Connected mailbox address.
        thread_id: Gmail thread id for deep-linking.
        subject: Decoded subject.
        sender: Raw sender address.
        received_at: Provider internal date.
        bucket: Primary triage bucket.
        confidence: Classification confidence in ``[0, 1]``.
        decision_source: Rule / LLM / hybrid source label.
        reasons: Human-readable rationale entries.
        summary_excerpt: Optional decrypted summary preview.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    account_email: EmailStr
    thread_id: str
    subject: str
    sender: str
    received_at: datetime
    bucket: EmailBucket
    confidence: float = Field(ge=0.0, le=1.0)
    decision_source: DecisionSource
    reasons: tuple[str, ...] = Field(default=())
    summary_excerpt: str | None = Field(default=None)


class EmailsListResponse(BaseModel):
    """Envelope for ``GET /emails``.

    Attributes:
        emails: Newest-first rows.
        total: Total matching rows before the response ``limit``.
    """

    model_config = ConfigDict(frozen=True)

    emails: tuple[EmailRowOut, ...] = Field(default=())
    total: int = Field(ge=0)


class EmailBucketPatchRequest(BaseModel):
    """Request body for ``PATCH /emails/{email_id}/bucket``.

    Attributes:
        bucket: User-selected destination bucket.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bucket: EmailBucket


__all__ = [
    "DecisionSource",
    "EmailBucket",
    "EmailBucketPatchRequest",
    "EmailRowOut",
    "EmailsListResponse",
]
