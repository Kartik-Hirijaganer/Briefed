"""Pydantic boundary models for email list and bucket-update APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

EmailBucket = Literal["must_read", "good_to_read", "ignore"]
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
        needs_review: Low-confidence badge source.
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
    needs_review: bool = Field(default=False)
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


class MarkReadRequest(BaseModel):
    """Request body for ``POST /emails/mark-read``.

    Attributes:
        email_ids: Explicit email ids to mark read.
        category: Optional category selector for bulk mark-read.
        account_id: Optional connected-account scope for either selector.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    email_ids: tuple[UUID, ...] = Field(default=())
    category: EmailBucket | None = Field(default=None)
    account_id: UUID | None = Field(default=None)

    @field_validator("email_ids")
    @classmethod
    def _dedupe_email_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Deduplicate explicit email ids while preserving order.

        Args:
            value: Incoming email ids.

        Returns:
            Deduplicated ids.
        """
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def _validate_selector(self) -> MarkReadRequest:
        """Require exactly one selector: explicit ids or a category.

        Returns:
            The validated request body.

        Raises:
            ValueError: If no selector or both selectors are provided.
        """
        if bool(self.email_ids) == (self.category is not None):
            raise ValueError("provide exactly one of email_ids or category")
        return self


class MarkReadFailureOut(BaseModel):
    """One email that could not be marked read.

    Attributes:
        email_id: Local email id.
        provider_message_id: Gmail message id.
        reason: Short provider or permission error.
    """

    model_config = ConfigDict(frozen=True)

    email_id: UUID
    provider_message_id: str
    reason: str


class MarkReadResponse(BaseModel):
    """Response from ``POST /emails/mark-read``.

    Attributes:
        marked: Count of local emails successfully marked read.
        failed: Per-email failures.
    """

    model_config = ConfigDict(frozen=True)

    marked: int = Field(ge=0)
    failed: tuple[MarkReadFailureOut, ...] = Field(default=())


class ErrorEnvelope(BaseModel):
    """Aegis-compatible API error response envelope.

    Attributes:
        code: Stable machine-readable error code.
        message: Human-readable error summary safe to show in the UI.
        details: Structured diagnostic context.
        request_id: Correlation id from the incoming request or generated locally.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    code: str = Field(..., description="Stable machine-readable error code.")
    message: str = Field(..., description="Human-readable error summary.")
    details: dict[str, object] = Field(default_factory=dict, description="Structured context.")
    request_id: str = Field(
        ...,
        serialization_alias="requestId",
        description="Request correlation id.",
    )


__all__ = [
    "DecisionSource",
    "EmailBucket",
    "EmailBucketPatchRequest",
    "EmailRowOut",
    "EmailsListResponse",
    "ErrorEnvelope",
    "MarkReadFailureOut",
    "MarkReadRequest",
    "MarkReadResponse",
]
