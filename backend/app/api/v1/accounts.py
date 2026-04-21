"""``/api/v1/accounts`` router — list + disconnect connected mailboxes.

Phase 1 exposes the minimum surface:

* ``GET    /api/v1/accounts`` → 200 + :class:`AccountsListResponse`.
* ``DELETE /api/v1/accounts/{account_id}`` → 204 (revokes upstream +
  deletes the row).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import current_user_id, db_session
from app.core.clock import utcnow
from app.db.models import ConnectedAccount, Email, SyncCursor
from app.schemas.accounts import (
    AccountsListResponse,
    ConnectedAccountOut,
    ConnectedAccountPatchRequest,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=AccountsListResponse, summary="List connected accounts")
async def list_accounts(
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> AccountsListResponse:
    """Return every connected account owned by ``user_id``.

    Args:
        user_id: Authenticated owner's id.
        session: Active async session.

    Returns:
        An :class:`AccountsListResponse` envelope.
    """
    account_rows = (
        (
            await session.execute(
                select(ConnectedAccount).where(ConnectedAccount.user_id == user_id),
            )
        )
        .scalars()
        .all()
    )
    account_ids = [acc.id for acc in account_rows]
    cursors: dict[UUID, object] = {}
    email_counts: dict[UUID, int] = {}
    if account_ids:
        cursors = {
            row.account_id: row.last_incremental_at
            for row in (
                (
                    await session.execute(
                        select(SyncCursor).where(SyncCursor.account_id.in_(account_ids)),
                    )
                )
                .scalars()
                .all()
            )
        }
        since = utcnow() - timedelta(hours=24)
        email_counts = {
            account_id: count
            for account_id, count in (
                await session.execute(
                    select(Email.account_id, func.count(Email.id))
                    .where(
                        Email.account_id.in_(account_ids),
                        Email.internal_date >= since,
                    )
                    .group_by(Email.account_id),
                )
            ).all()
        }
    items = tuple(
        ConnectedAccountOut(
            id=acc.id,
            email=acc.email,
            display_name=None,
            provider=acc.provider,
            status=acc.status,
            auto_scan_enabled=acc.auto_scan_enabled,
            exclude_from_global_digest=acc.exclude_from_global_digest,
            created_at=acc.created_at,
            last_sync_at=cursors.get(acc.id),  # type: ignore[arg-type]
            emails_ingested_24h=email_counts.get(acc.id, 0),
            daily_budget_used_pct=0.0,
        )
        for acc in account_rows
    )
    return AccountsListResponse(accounts=items)


@router.patch(
    "/{account_id}",
    response_model=ConnectedAccountOut,
    summary="Update account settings",
)
async def patch_account(
    account_id: UUID,
    payload: ConnectedAccountPatchRequest,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> ConnectedAccountOut:
    """Update per-account UI preferences.

    Args:
        account_id: Target account.
        payload: Patch body.
        user_id: Authenticated owner's id.
        session: Active async session.

    Returns:
        Updated account view.

    Raises:
        HTTPException: 404 when the account does not belong to the caller.
    """
    account = await session.get(ConnectedAccount, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account not found")
    if payload.auto_scan_enabled is not None:
        account.auto_scan_enabled = payload.auto_scan_enabled
    if payload.exclude_from_global_digest is not None:
        account.exclude_from_global_digest = payload.exclude_from_global_digest
    await session.flush()
    cursor = await session.get(SyncCursor, account.id)
    return ConnectedAccountOut(
        id=account.id,
        email=account.email,
        display_name=payload.display_name,
        provider=account.provider,
        status=account.status,
        auto_scan_enabled=account.auto_scan_enabled,
        exclude_from_global_digest=account.exclude_from_global_digest,
        created_at=account.created_at,
        last_sync_at=cursor.last_incremental_at if cursor else None,
        emails_ingested_24h=0,
        daily_budget_used_pct=0.0,
    )


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect a mailbox",
)
async def delete_account(
    account_id: UUID,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Disconnect ``account_id`` (soft-cascade deletes tokens + cursor + emails).

    Args:
        account_id: Target account.
        user_id: Authenticated owner's id.
        session: Active async session.

    Raises:
        HTTPException: 404 when the account does not belong to the caller.
    """
    account = await session.get(ConnectedAccount, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account not found")
    await session.delete(account)
