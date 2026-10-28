"""Gmail sync-cursor lifecycle: bootstrap scan → History API on the next run.

Regression: a bootstrap scan persisted ``stale=True``, so every later run
rescanned the lookback window instead of using ``users.history.list``.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConnectedAccount, User
from app.db.models import SyncCursor as SyncCursorRow
from app.domain.providers import ProviderCredentials, SyncCursor
from app.services.gmail.client import GmailClient
from app.services.gmail.provider import GmailProvider
from app.services.ingestion.pipeline import run_ingest


class _GmailFake(httpx.AsyncBaseTransport):
    """Route Gmail REST calls to an in-memory mailbox and log each call."""

    def __init__(self) -> None:
        self.watermark = 100
        self.listed: list[str] = []
        self.history: list[dict[str, Any]] = []
        self.history_status = 200
        self.labels: dict[str, list[str]] = {}
        self.calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Answer one Gmail request from the fake mailbox state."""
        path = request.url.path.rsplit("/users/me", 1)[-1]
        params = request.url.params
        if path == "/profile":
            self.calls.append("profile")
            return httpx.Response(200, json={"historyId": str(self.watermark)})
        if path == "/history":
            self.calls.append(f"history:{params['startHistoryId']}")
            if self.history_status != 200:
                return httpx.Response(self.history_status, json={})
            return httpx.Response(
                200,
                json={"history": self.history, "historyId": str(self.watermark)},
            )
        if path == "/messages":
            self.calls.append(f"list:{params['q']}")
            return httpx.Response(200, json={"messages": [{"id": i} for i in self.listed]})
        message_id = path.removeprefix("/messages/")
        if params["format"] == "minimal":
            self.calls.append(f"labels:{message_id}")
            return httpx.Response(200, json={"labelIds": self.labels[message_id]})
        self.calls.append(f"get:{message_id}")
        return httpx.Response(200, json=_raw_payload(message_id, self.labels[message_id]))


@pytest.mark.parametrize(
    "seed_cursor",
    [None, (50, True)],
    ids=["first-connect", "legacy-stale-row"],
)
async def test_bootstrap_run_hands_next_run_to_history_api(
    test_session: AsyncSession,
    seed_cursor: tuple[int, bool] | None,
) -> None:
    """After one bounded bootstrap, the next run reads ``users.history.list``.

    ``legacy-stale-row`` mirrors stuck prod accounts: one more bootstrap,
    then incremental.
    """
    account_id = await _seed_account(test_session, seed_cursor=seed_cursor)
    gmail = _GmailFake()
    gmail.listed = ["m1"]
    gmail.labels = {"m1": ["INBOX", "UNREAD"], "m2": ["INBOX", "UNREAD"]}

    async with httpx.AsyncClient(transport=gmail) as http:
        provider = _provider(http, unread_only=True)
        first = await run_ingest(
            session=test_session,
            account_id=account_id,
            provider=provider,
            credentials=_credentials(account_id),
        )
        await test_session.commit()

        row = await test_session.get(SyncCursorRow, account_id)
        assert row is not None
        assert first.cursor_stale is True
        assert first.new == 1
        assert (row.history_id, row.stale) == (100, False)
        assert row.last_full_sync_at is not None

        gmail.calls.clear()
        gmail.watermark = 105
        gmail.history = [{"messagesAdded": [{"message": {"id": "m2"}}]}]
        second = await run_ingest(
            session=test_session,
            account_id=account_id,
            provider=provider,
            credentials=_credentials(account_id),
        )
        await test_session.commit()

    assert gmail.calls == ["history:100", "labels:m2", "get:m2"]
    assert second.cursor_stale is False
    assert (second.new, second.duplicates) == (1, 0)
    await test_session.refresh(row)
    assert (row.history_id, row.stale) == (105, False)


async def test_bootstrap_reads_watermark_before_listing() -> None:
    """The watermark predates the scan, so mail landing mid-scan is not skipped."""
    gmail = _GmailFake()
    gmail.listed = ["m1"]
    async with httpx.AsyncClient(transport=gmail) as http:
        ids, cursor = await _provider(http, unread_only=True).list_new_ids(
            _credentials(uuid4()),
            SyncCursor(account_id=uuid4()),
        )

    assert ids == ["m1"]
    assert gmail.calls == ["profile", "list:is:unread newer_than:14d"]
    assert (cursor.history_id, cursor.stale) == (100, True)


async def test_expired_history_cursor_falls_back_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A history 404 runs the bounded scan and leaves a log line behind."""
    events: list[tuple[str, dict[str, Any]]] = []

    class _Logger:
        def warning(self, event: str, **kwargs: Any) -> None:
            events.append((event, kwargs))

    monkeypatch.setattr("app.services.gmail.provider.logger", _Logger())
    gmail = _GmailFake()
    gmail.history_status = 404
    gmail.listed = ["m1"]
    account_id = uuid4()
    async with httpx.AsyncClient(transport=gmail) as http:
        ids, cursor = await _provider(http, unread_only=True).list_new_ids(
            _credentials(account_id),
            SyncCursor(account_id=account_id, history_id=7),
        )

    assert ids == ["m1"]
    assert gmail.calls == ["history:7", "profile", "list:is:unread newer_than:14d"]
    assert (cursor.history_id, cursor.stale) == (100, True)
    assert events == [
        (
            "gmail.history_cursor_expired",
            {"account_id": str(account_id), "start_history_id": 7},
        ),
    ]


@pytest.mark.parametrize("unread_only", [True, False], ids=["unread-only", "all-mail"])
async def test_history_path_skips_spam_and_trash(*, unread_only: bool) -> None:
    """History ids match the bootstrap scan, which never returns Spam or Trash."""
    gmail = _GmailFake()
    gmail.history = [
        {
            "messagesAdded": [
                {"message": {"id": "inbox", "labelIds": ["INBOX", "UNREAD"]}},
                {"message": {"id": "spam", "labelIds": ["SPAM", "UNREAD"]}},
                {"message": {"id": "binned", "labelIds": ["INBOX", "UNREAD"]}},
            ],
        },
    ]
    # ``binned`` was trashed after it arrived: only its live labels say so.
    gmail.labels = {"inbox": ["INBOX", "UNREAD"], "binned": ["TRASH", "UNREAD"]}
    async with httpx.AsyncClient(transport=gmail) as http:
        ids, _cursor = await _provider(http, unread_only=unread_only).list_new_ids(
            _credentials(uuid4()),
            SyncCursor(account_id=uuid4(), history_id=5),
        )

    assert ids == (["inbox"] if unread_only else ["inbox", "binned"])


def _provider(http: httpx.AsyncClient, *, unread_only: bool) -> GmailProvider:
    """Build a provider over the fake transport with a 14-day lookback."""
    return GmailProvider(
        client=GmailClient(http_client=http),
        http_client=http,
        bootstrap_lookback_days=14,
        unread_only=unread_only,
    )


def _raw_payload(message_id: str, labels: list[str]) -> dict[str, Any]:
    """Return a ``format=raw`` Gmail payload for a one-line plain-text email."""
    mime = (
        f"Subject: {message_id}\r\nFrom: alice@example.com\r\n"
        f"Content-Type: text/plain\r\n\r\nbody-{message_id}"
    ).encode()
    return {
        "id": message_id,
        "threadId": f"t-{message_id}",
        "internalDate": "1700000000000",
        "sizeEstimate": len(mime),
        "snippet": f"body-{message_id}",
        "labelIds": labels,
        "raw": base64.urlsafe_b64encode(mime).decode(),
    }


async def _seed_account(
    session: AsyncSession,
    *,
    seed_cursor: tuple[int, bool] | None,
) -> UUID:
    """Insert a user + Gmail account, plus a ``(history_id, stale)`` cursor row if given."""
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
    await session.flush()
    if seed_cursor is not None:
        history_id, stale = seed_cursor
        session.add(SyncCursorRow(account_id=account.id, history_id=history_id, stale=stale))
    await session.commit()
    return account.id


def _credentials(account_id: UUID) -> ProviderCredentials:
    """Return unexpired placeholder credentials for ``account_id``."""
    return ProviderCredentials(
        account_id=account_id,
        access_token="a",
        refresh_token="r",
        scope=("gmail.readonly",),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
