"""``/api/v1/accounts`` router — list, disconnect, and remove mailboxes.

The accounts lifecycle intentionally separates local access revocation from
removing the account row:

* ``GET    /api/v1/accounts`` → 200 + :class:`AccountsListResponse`.
* ``POST   /api/v1/accounts/{account_id}/disconnect`` → 200 + revoked row.
* ``DELETE /api/v1/accounts/{account_id}`` → 204, only after disconnect.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update

from app.api.deps import current_user_id, db_session
from app.core.clock import utcnow
from app.db.models import (
    Classification,
    ConnectedAccount,
    DigestRunEmail,
    Email,
    EmailContentBlob,
    OAuthToken,
    PromptCallLog,
    Summary,
    SyncCursor,
    TechNewsClusterMember,
    UnsubscribeSuggestion,
)
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
    cursors: dict[UUID, datetime | None] = {}
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
        _account_out(
            account=acc,
            last_sync_at=cursors.get(acc.id),
            emails_ingested_24h=email_counts.get(acc.id, 0),
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


@router.post(
    "/{account_id}/disconnect",
    response_model=ConnectedAccountOut,
    summary="Disconnect a mailbox",
)
async def disconnect_account(
    account_id: UUID,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> ConnectedAccountOut:
    """Disconnect an account while keeping it available for reconnect/remove.

    The operation removes Briefed's local OAuth grant and account-scoped
    cached data, then marks the account ``revoked`` so the UI can offer a
    reconnect or final remove action. It is safe to call repeatedly.

    Args:
        account_id: Target account.
        user_id: Authenticated owner's id.
        session: Active async session.

    Returns:
        The updated revoked account view.

    Raises:
        HTTPException: 404 when the account does not belong to the caller.
    """
    account = await _load_owned_account(
        session=session,
        account_id=account_id,
        user_id=user_id,
    )
    await _purge_account_runtime_data(session=session, account_id=account.id)
    account.status = "revoked"
    account.auto_scan_enabled = False
    await session.flush()
    return _account_out(account=account, last_sync_at=None, emails_ingested_24h=0)


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a disconnected mailbox",
)
async def delete_account(
    account_id: UUID,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Remove ``account_id`` after it has been disconnected.

    Args:
        account_id: Target account.
        user_id: Authenticated owner's id.
        session: Active async session.

    Raises:
        HTTPException: 404 when the account does not belong to the caller.
        HTTPException: 409 when the account is still active.
    """
    account = await _load_owned_account(
        session=session,
        account_id=account_id,
        user_id=user_id,
    )
    if account.status == "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="disconnect account before removing it",
        )
    await session.delete(account)


async def _load_owned_account(
    *,
    session: AsyncSession,
    account_id: UUID,
    user_id: UUID,
) -> ConnectedAccount:
    """Load an account and enforce caller ownership.

    Args:
        session: Active async session.
        account_id: Account id to load.
        user_id: Authenticated owner's id.

    Returns:
        The owned :class:`ConnectedAccount`.

    Raises:
        HTTPException: 404 when the account is missing or owned by another user.
    """
    account = await session.get(ConnectedAccount, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="account not found")
    return account


async def _purge_account_runtime_data(*, session: AsyncSession, account_id: UUID) -> None:
    """Delete local access and account-scoped cached data for disconnect.

    Args:
        session: Active async session.
        account_id: Account whose local runtime data should be removed.
    """
    email_ids = select(Email.id).where(Email.account_id == account_id)
    await session.execute(delete(OAuthToken).where(OAuthToken.account_id == account_id))
    await session.execute(delete(SyncCursor).where(SyncCursor.account_id == account_id))
    await session.execute(
        delete(UnsubscribeSuggestion).where(UnsubscribeSuggestion.account_id == account_id),
    )
    await session.execute(
        update(PromptCallLog)
        .where(PromptCallLog.email_id.in_(email_ids))
        .values(email_id=None)
        .execution_options(synchronize_session=False),
    )
    await session.execute(
        delete(DigestRunEmail)
        .where(DigestRunEmail.email_id.in_(email_ids))
        .execution_options(synchronize_session=False),
    )
    await session.execute(
        delete(TechNewsClusterMember)
        .where(TechNewsClusterMember.email_id.in_(email_ids))
        .execution_options(synchronize_session=False),
    )
    await session.execute(
        delete(Summary)
        .where(Summary.email_id.in_(email_ids))
        .execution_options(synchronize_session=False),
    )
    await session.execute(
        delete(Classification)
        .where(Classification.email_id.in_(email_ids))
        .execution_options(synchronize_session=False),
    )
    await session.execute(
        delete(EmailContentBlob)
        .where(EmailContentBlob.message_id.in_(email_ids))
        .execution_options(synchronize_session=False),
    )
    await session.execute(delete(Email).where(Email.account_id == account_id))


def _account_out(
    *,
    account: ConnectedAccount,
    last_sync_at: datetime | None,
    emails_ingested_24h: int,
) -> ConnectedAccountOut:
    """Build the public account DTO from an ORM row and computed fields.

    Args:
        account: Connected-account ORM row.
        last_sync_at: Latest sync timestamp, if any.
        emails_ingested_24h: Count of recent locally cached emails.

    Returns:
        Public account response model.
    """
    return ConnectedAccountOut(
        id=account.id,
        email=account.email,
        display_name=None,
        provider=account.provider,
        status=account.status,
        auto_scan_enabled=account.auto_scan_enabled,
        exclude_from_global_digest=account.exclude_from_global_digest,
        created_at=account.created_at,
        last_sync_at=last_sync_at,
        emails_ingested_24h=emails_ingested_24h,
        daily_budget_used_pct=0.0,
    )
