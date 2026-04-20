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
        provider: Always ``"gmail"`` in 1.0.0.
        status: Lifecycle state (``active``/``disabled``/``revoked``).
        created_at: When the account was connected.
        last_sync_at: Latest successful ingest timestamp, if any.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    email: EmailStr
    provider: str = Field(default="gmail")
    status: str
    created_at: datetime
    last_sync_at: datetime | None = Field(default=None)


class AccountsListResponse(BaseModel):
    """Envelope wrapping the ``GET /accounts`` list.

    Attributes:
        accounts: Every :class:`ConnectedAccountOut` owned by the caller.
    """

    model_config = ConfigDict(frozen=True)

    accounts: tuple[ConnectedAccountOut, ...] = Field(default=())
