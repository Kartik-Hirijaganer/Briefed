"""Integration tests for Gmail mailbox provider behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx

from app.domain.providers import ProviderCredentials, SyncCursor
from app.services.gmail.client import GmailClient
from app.services.gmail.provider import GmailProvider


class _ScriptedTransport(httpx.AsyncBaseTransport):
    """httpx transport that returns scripted responses in order."""

    def __init__(self, responses: list[tuple[int, dict[str, Any] | str]]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return the next scripted response.

        Args:
            request: Outgoing request.

        Returns:
            Scripted HTTP response.
        """
        self.requests.append(request)
        status, body = self._responses.pop(0)
        if isinstance(body, dict):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body)


async def test_history_path_filters_messages_without_unread() -> None:
    """Unread-only incremental scans drop history-added read messages."""
    transport = _ScriptedTransport(
        responses=[
            (
                200,
                {
                    "history": [
                        {"messagesAdded": [{"message": {"id": "m1"}}, {"message": {"id": "m2"}}]}
                    ],
                    "historyId": "10",
                },
            ),
            (200, {"labelIds": ["INBOX", "UNREAD"]}),
            (200, {"labelIds": ["INBOX"]}),
        ],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        provider = GmailProvider(
            client=GmailClient(http_client=http),
            http_client=http,
            unread_only=True,
        )
        ids, cursor = await provider.list_new_ids(
            _credentials(),
            SyncCursor(account_id=uuid4(), history_id=5),
        )

    assert ids == ["m1"]
    assert cursor.history_id == 10


async def test_bootstrap_query_is_unread_when_configured() -> None:
    """Unread-only bootstrap scans use Gmail's server-side unread query."""
    transport = _ScriptedTransport(
        responses=[
            (200, {"messages": [{"id": "m1"}]}),
            (200, {"historyId": "10"}),
        ],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        provider = GmailProvider(
            client=GmailClient(http_client=http),
            http_client=http,
            bootstrap_lookback_days=14,
            unread_only=True,
        )
        ids, _cursor = await provider.list_new_ids(
            _credentials(),
            SyncCursor(account_id=uuid4()),
        )

    assert ids == ["m1"]
    assert "q=is%3Aunread+newer_than%3A14d" in str(transport.requests[0].url)


async def test_mark_read_falls_back_to_singletons_after_batch_failure() -> None:
    """A failed Gmail batch is isolated into per-message failures."""
    transport = _ScriptedTransport(
        responses=[
            (400, "bad batch"),
            (204, ""),
            (404, "missing"),
        ],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        provider = GmailProvider(client=GmailClient(http_client=http), http_client=http)
        result = await provider.mark_read(_credentials(), ["m1", "m2"])

    assert result.marked == ("m1",)
    assert len(result.failed) == 1
    assert result.failed[0].message_id == "m2"
    assert all(request.method == "POST" for request in transport.requests)


def _credentials() -> ProviderCredentials:
    """Return non-expired Gmail credentials for provider tests."""
    return ProviderCredentials(
        account_id=uuid4(),
        access_token="access",
        refresh_token="refresh",
        scope=("https://www.googleapis.com/auth/gmail.modify",),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
