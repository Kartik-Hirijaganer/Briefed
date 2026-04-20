"""``/api/v1/accounts`` router — list + disconnect connected mailboxes.

Phase 1 exposes the minimum surface:

* ``GET    /api/v1/accounts`` → 200 + :class:`AccountsListResponse`.
* ``DELETE /api/v1/accounts/{account_id}`` → 204 (revokes upstream +
  deletes the row).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import current_user_id, db_session
from app.db.models import ConnectedAccount, SyncCursor
from app.schemas.accounts import AccountsListResponse, ConnectedAccountOut

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
    cursors = {
        row.account_id: row.last_incremental_at
        for row in (
            (
                await session.execute(
                    select(SyncCursor).where(
                        SyncCursor.account_id.in_([acc.id for acc in account_rows]),
                    ),
                )
            )
            .scalars()
            .all()
        )
    }
    items = tuple(
        ConnectedAccountOut(
            id=acc.id,
            email=acc.email,
            provider=acc.provider,
            status=acc.status,
            created_at=acc.created_at,
            last_sync_at=cursors.get(acc.id),
        )
        for acc in account_rows
    )
    return AccountsListResponse(accounts=items)


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
