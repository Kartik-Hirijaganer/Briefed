"""Integration tests for the Phase 1 ingestion pipeline (plan §14)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConnectedAccount, Email, User
from app.db.models import SyncCursor as SyncCursorRow
from app.domain.providers import (
    MailboxProvider,
    MessageId,
    ProviderCredentials,
    RawMessage,
    SyncCursor,
)
from app.services.ingestion.pipeline import run_ingest
from app.services.ingestion.storage import InMemoryObjectStore


@dataclass
class _FakeGmail(MailboxProvider):
    """A :class:`MailboxProvider` stub driven by in-memory fixtures."""

    kind: Literal["gmail", "outlook", "imap"] = "gmail"
    messages: dict[MessageId, RawMessage] = field(default_factory=dict)
    stale_on_first_call: bool = False
    _first_list_done: bool = False

    async def list_new_ids(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> tuple[list[MessageId], SyncCursor]:
        if self.stale_on_first_call and not self._first_list_done:
            self._first_list_done = True
            return (
                list(self.messages.keys()),
                cursor.model_copy(update={"history_id": 42, "stale": True}),
            )
        return (
            list(self.messages.keys()),
            cursor.model_copy(update={"history_id": 42, "stale": False}),
        )

    async def get_messages(
        self,
        credentials: ProviderCredentials,
        ids: list[MessageId],
    ) -> list[RawMessage]:
        return [self.messages[i] for i in ids if i in self.messages]

    async def refresh_cursor(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> SyncCursor:
        return cursor.model_copy(update={"stale": False})

    async def revoke(self, credentials: ProviderCredentials) -> None:
        return None


def _make_fixture_emails(count: int) -> dict[MessageId, RawMessage]:
    out: dict[MessageId, RawMessage] = {}
    for i in range(count):
        mid = f"m-{i:04d}"
        mime = (
            f"Subject: Fixture {i}\r\n"
            f"From: alice@example.com\r\n"
            "Content-Type: text/plain\r\n\r\n"
            f"body-{i}"
        ).encode()
        out[mid] = RawMessage(
            message_id=mid,
            thread_id=f"t-{i:04d}",
            internal_date_ms=1_700_000_000_000 + i,
            raw_mime=mime,
            size_bytes=len(mime),
            snippet=f"body-{i}",
        )
    return out


async def _seed_account(session: AsyncSession) -> UUID:
    user = User(email="owner@example.com", tz="UTC", status="active")
    session.add(user)
    await session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="owner@example.com",
        status="active",
    )
    session.add(account)
    await session.commit()
    return account.id


def _credentials(account_id: UUID) -> ProviderCredentials:
    from datetime import UTC, datetime, timedelta

    return ProviderCredentials(
        account_id=account_id,
        access_token="a",
        refresh_token="r",
        scope=("gmail.readonly",),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


async def test_ingest_100_emails_enforces_unique(test_session: AsyncSession) -> None:
    """Plan §14 Phase 1: ingest 100 emails, assert UNIQUE, re-run is no-op."""
    account_id = await _seed_account(test_session)
    provider = _FakeGmail(messages=_make_fixture_emails(100))

    stats = await run_ingest(
        session=test_session,
        account_id=account_id,
        provider=provider,
        credentials=_credentials(account_id),
    )
    await test_session.commit()
    assert stats.new == 100
    assert stats.duplicates == 0

    count = (
        await test_session.execute(
            select(func.count()).select_from(Email).where(Email.account_id == account_id),
        )
    ).scalar_one()
    assert count == 100

    # Re-run: provider returns the same ids, nothing new should land.
    stats2 = await run_ingest(
        session=test_session,
        account_id=account_id,
        provider=provider,
        credentials=_credentials(account_id),
    )
    await test_session.commit()
    assert stats2.new == 0
    assert stats2.duplicates == 100

    count_after = (
        await test_session.execute(
            select(func.count()).select_from(Email).where(Email.account_id == account_id),
        )
    ).scalar_one()
    assert count_after == 100


async def test_ingest_stale_cursor_surfaces_bounded_full_sync(
    test_session: AsyncSession,
) -> None:
    """Plan Phase 1 — 'stale cursor detected, bounded full sync runs'."""
    account_id = await _seed_account(test_session)
    provider = _FakeGmail(
        messages=_make_fixture_emails(5),
        stale_on_first_call=True,
    )

    stats = await run_ingest(
        session=test_session,
        account_id=account_id,
        provider=provider,
        credentials=_credentials(account_id),
    )
    await test_session.commit()
    assert stats.cursor_stale is True

    cursor = await test_session.get(SyncCursorRow, account_id)
    assert cursor is not None
    assert cursor.stale is True
    assert cursor.last_full_sync_at is not None


async def test_ingest_with_raw_mime_toggle_uploads_s3(
    test_session: AsyncSession,
) -> None:
    account_id = await _seed_account(test_session)
    provider = _FakeGmail(messages=_make_fixture_emails(3))
    store = InMemoryObjectStore()

    stats = await run_ingest(
        session=test_session,
        account_id=account_id,
        provider=provider,
        credentials=_credentials(account_id),
        raw_storage=store,
        raw_bucket="briefed-raw",
        store_raw_mime=True,
    )
    await test_session.commit()

    assert stats.raw_uploaded == 3
    assert len(store.objects) == 3
    for (bucket, _key), body in store.objects.items():
        assert bucket == "briefed-raw"
        assert b"Content-Type: text/plain" in body


async def test_ingest_missing_account_raises(test_session: AsyncSession) -> None:
    provider = _FakeGmail(messages=_make_fixture_emails(1))
    with pytest.raises(LookupError):
        await run_ingest(
            session=test_session,
            account_id=uuid4(),
            provider=provider,
            credentials=_credentials(uuid4()),
        )


async def test_existing_hashes_round_trip(test_session: AsyncSession) -> None:
    from app.services.ingestion.dedup import existing_message_hashes

    account_id = await _seed_account(test_session)
    provider = _FakeGmail(messages=_make_fixture_emails(3))
    await run_ingest(
        session=test_session,
        account_id=account_id,
        provider=provider,
        credentials=_credentials(account_id),
    )
    await test_session.commit()

    hashes = await existing_message_hashes(
        test_session,
        account_id=account_id,
        message_ids=["m-0000", "m-0001", "absent"],
    )
    assert set(hashes.keys()) == {"m-0000", "m-0001"}
    for digest in hashes.values():
        assert len(digest) == 32
