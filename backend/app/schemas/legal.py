"""Pydantic models for legal-consent API boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LegalConsentRequiredError(BaseModel):
    """Error body returned when current legal consent is required.

    Attributes:
        detail: Stable FastAPI ``HTTPException`` detail string.
    """

    model_config = ConfigDict(frozen=True)

    detail: Literal["legal_consent_required"] = Field(
        ...,
        description="Stable error detail for stale or missing legal consent.",
    )


class LegalConsentStatusOut(BaseModel):
    """Current caller's legal-consent status.

    Attributes:
        current_privacy_policy_version: Backend-required privacy policy version.
        current_terms_version: Backend-required terms of service version.
        accepted_privacy_policy_version: Highest privacy policy version the user accepted.
        accepted_terms_version: Highest terms of service version the user accepted.
        consent_required: Whether the user must accept current policies before processing.
        accepted_at: Timestamp of the latest legal acceptance, if any.
    """

    model_config = ConfigDict(frozen=True)

    current_privacy_policy_version: int = Field(
        ...,
        ge=1,
        description="Backend-required privacy policy version.",
    )
    current_terms_version: int = Field(
        ...,
        ge=1,
        description="Backend-required terms of service version.",
    )
    accepted_privacy_policy_version: int = Field(
        ...,
        ge=0,
        description="Highest privacy policy version accepted by the user.",
    )
    accepted_terms_version: int = Field(
        ...,
        ge=0,
        description="Highest terms of service version accepted by the user.",
    )
    consent_required: bool = Field(
        ...,
        description="Whether current legal consent is required before Gmail processing.",
    )
    accepted_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the latest legal acceptance.",
    )


class LegalConsentRequest(BaseModel):
    """Request body for accepting the current policies.

    Attributes:
        privacy_policy_version: Privacy policy version shown to the user.
        terms_version: Terms of service version shown to the user.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    privacy_policy_version: int = Field(
        ...,
        ge=1,
        description="Privacy policy version the user is accepting.",
    )
    terms_version: int = Field(
        ...,
        ge=1,
        description="Terms of service version the user is accepting.",
    )


__all__ = ["LegalConsentRequest", "LegalConsentRequiredError", "LegalConsentStatusOut"]
