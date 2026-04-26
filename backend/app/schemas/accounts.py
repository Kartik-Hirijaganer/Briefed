"""Pydantic boundary models for the accounts API (plan §10).

Phase 1 exposes a minimal ``/api/v1/accounts`` surface:

* ``GET  /accounts`` — list all connected accounts for the authenticated owner.
* ``POST /accounts`` — normally driven by the OAuth callback, not the user.
* ``DELETE /accounts/{id}`` — disconnect + revoke.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ConnectedAccountOut(BaseModel):
    """Public view of a ``connected_accounts`` row.

    Attributes:
        id: ``connected_accounts.id``.
        email: Mailbox address.
        display_name: Optional UI label. ``None`` falls back to email.
        provider: Always ``"gmail"`` in 1.0.0.
        status: Lifecycle state (``active``/``disabled``/``revoked``).
        auto_scan_enabled: Per-account scan switch.
        exclude_from_global_digest: Per-account digest opt-out.
        created_at: When the account was connected.
        last_sync_at: Latest successful ingest timestamp, if any.
        emails_ingested_24h: Count for the settings card.
        daily_budget_used_pct: Approximate daily token budget usage.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    email: EmailStr
    display_name: str | None = Field(default=None)
    provider: str = Field(default="gmail")
    status: str
    auto_scan_enabled: bool = Field(default=True)
    exclude_from_global_digest: bool = Field(default=False)
    created_at: datetime
    last_sync_at: datetime | None = Field(default=None)
    emails_ingested_24h: int = Field(default=0, ge=0)
    daily_budget_used_pct: float = Field(default=0.0, ge=0.0)


class ConnectedAccountPatchRequest(BaseModel):
    """Request body for ``PATCH /accounts/{account_id}``.

    Attributes:
        auto_scan_enabled: Toggle scans for this account.
        exclude_from_global_digest: Toggle the global-digest opt-out.
        display_name: Accepted for forward compatibility; ignored in
            1.0.0 because connected-account rows do not store aliases.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    auto_scan_enabled: bool | None = Field(default=None)
    exclude_from_global_digest: bool | None = Field(default=None)
    display_name: str | None = Field(default=None, max_length=255)


class AccountsListResponse(BaseModel):
    """Envelope wrapping the ``GET /accounts`` list.

    Attributes:
        accounts: Every :class:`ConnectedAccountOut` owned by the caller.
    """

    model_config = ConfigDict(frozen=True)

    accounts: tuple[ConnectedAccountOut, ...] = Field(default=())


__all__ = [
    "AccountsListResponse",
    "ConnectedAccountOut",
    "ConnectedAccountPatchRequest",
]
