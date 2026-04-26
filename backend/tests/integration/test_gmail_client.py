"""Integration tests for :class:`GmailClient` (429 backoff, history/list)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.errors import QuotaExceededError, StaleCursorError
from app.services.gmail.client import GmailClient


class _ScriptedTransport(httpx.AsyncBaseTransport):
    """httpx transport that returns scripted responses in order."""

    def __init__(self, responses: list[tuple[int, dict[str, Any] | str]]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self._responses.pop(0)
        if isinstance(body, dict):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body)


async def test_429_triggers_retry_then_succeeds() -> None:
    """Plan Phase 1 — 'simulated 429 triggers backoff; retry succeeds'."""
    transport = _ScriptedTransport(
        responses=[
            (429, "too fast"),
            (429, "too fast"),
            (200, {"history": [], "historyId": "100"}),
        ]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = GmailClient(http_client=http)
        added, next_id = await client.list_history(
            access_token="a",
            start_history_id=50,
        )
    assert added == []
    assert next_id == 100
    # Three HTTP calls — two 429s plus the final 200.
    assert len(transport.requests) == 3


async def test_persistent_429_eventually_raises() -> None:
    transport = _ScriptedTransport(
        responses=[(429, "stop") for _ in range(10)],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = GmailClient(http_client=http)
        with pytest.raises(QuotaExceededError):
            await client.list_history(access_token="a", start_history_id=1)


async def test_404_on_history_raises_stale_cursor() -> None:
    transport = _ScriptedTransport(responses=[(404, "gone")])
    async with httpx.AsyncClient(transport=transport) as http:
        client = GmailClient(http_client=http)
        with pytest.raises(StaleCursorError):
            await client.list_history(access_token="a", start_history_id=1)


async def test_list_messages_paginates() -> None:
    transport = _ScriptedTransport(
        responses=[
            (200, {"messages": [{"id": "m1"}], "nextPageToken": "p2"}),
            (200, {"messages": [{"id": "m2"}]}),
        ]
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = GmailClient(http_client=http)
        collected: list[str] = []
        async for mid in client.list_messages(
            access_token="a",
            query="newer_than:7d",
        ):
            collected.append(mid)
    assert collected == ["m1", "m2"]


async def test_get_profile_history_id_roundtrip() -> None:
    transport = _ScriptedTransport(
        responses=[(200, {"historyId": "999"})],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = GmailClient(http_client=http)
        value = await client.get_profile_history_id(access_token="a")
    assert value == 999


async def test_get_message_raw_propagates_errors() -> None:
    from app.services.gmail.client import GmailApiError

    transport = _ScriptedTransport(responses=[(403, "nope")])
    async with httpx.AsyncClient(transport=transport) as http:
        client = GmailClient(http_client=http)
        with pytest.raises(GmailApiError):
            await client.get_message_raw(access_token="a", message_id="m")
