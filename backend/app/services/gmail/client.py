"""Thin HTTP client over Gmail REST APIs (plan §7 Gmail integration layer).

Owns:

* ``users.history.list`` — driven by :attr:`SyncCursor.history_id`.
* ``users.messages.list`` — bounded fallback when the cursor is stale.
* ``users.messages.get`` — per-message fetch in ``format=raw`` so the
  MIME parser can pull List-Unsubscribe + encoded-word subjects.

Every call passes through a :class:`TokenBucket` (plan §14 Phase 1 —
"quota-aware token bucket") and a tenacity retry loop that backs off on
HTTP 429 / 5xx until the decorator's stop-condition fires.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.errors import ProviderError, QuotaExceededError, StaleCursorError
from app.services.gmail.ratelimit import TokenBucket

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterator


API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
"""Gmail REST base path when authorized as the end-user."""

_DEFAULT_PAGE_SIZE = 500
"""Max ``maxResults`` accepted by ``messages.list``."""


class GmailApiError(ProviderError):
    """Upstream Gmail API returned an unrecoverable error."""


class GmailClient:
    """Quota-aware Gmail REST client.

    Args:
        http_client: Pre-built :class:`httpx.AsyncClient`.
        bucket: Per-account token bucket. Defaults to 5 requests / sec
            (well inside Google's 250 quota-units/user/sec ceiling for
            metadata ops).
    """

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        bucket: TokenBucket | None = None,
    ) -> None:
        """Store collaborators. Never opens a connection at construction."""
        self._client = http_client
        self._bucket = bucket or TokenBucket(capacity=5.0, refill_rate=5.0)

    async def list_history(
        self,
        *,
        access_token: str,
        start_history_id: int,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Call ``users.history.list`` and return added-message entries.

        Args:
            access_token: Bearer token authenticating as the mailbox owner.
            start_history_id: ``historyId`` to resume from (exclusive).
            page_size: ``maxResults`` forwarded to Gmail.

        Returns:
            A ``(added_messages, next_history_id)`` pair. ``added_messages``
            is the flattened list of ``messagesAdded`` entries across
            pages; ``next_history_id`` is the ``historyId`` high-water
            mark to persist on the cursor.

        Raises:
            StaleCursorError: Gmail returned 404 — the cursor is older
                than the ~7-day history retention window and the caller
                must fall back to a bounded ``messages.list`` scan.
            QuotaExceededError: The bucket retries exhausted on 429s.
            GmailApiError: Any other non-2xx response.
        """
        added: list[dict[str, Any]] = []
        next_history: int | None = start_history_id
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "startHistoryId": str(start_history_id),
                "maxResults": page_size,
                "historyTypes": "messageAdded",
            }
            if page_token:
                params["pageToken"] = page_token
            response = await self._get("/history", access_token, params)
            if response.status_code == 404:
                raise StaleCursorError(
                    f"Gmail history cursor {start_history_id} is older than retention",
                )
            self._raise_for_status(response)
            payload = response.json()
            for record in payload.get("history") or ():
                for entry in record.get("messagesAdded") or ():
                    message = entry.get("message") or {}
                    added.append(message)
            advisory = payload.get("historyId")
            if advisory is not None:
                next_history = int(advisory)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return added, next_history

    async def list_messages(
        self,
        *,
        access_token: str,
        query: str,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> AsyncIterator[str]:
        """Yield message ids from a ``messages.list`` query.

        Used both for the first-time bootstrap and the stale-cursor
        fallback (plan §19.15 — bounded lookback).

        Args:
            access_token: Bearer token.
            query: Gmail search query (e.g. ``"newer_than:14d"``).
            page_size: ``maxResults`` forwarded to Gmail.

        Yields:
            Message ids as strings.
        """
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"q": query, "maxResults": page_size}
            if page_token:
                params["pageToken"] = page_token
            response = await self._get("/messages", access_token, params)
            self._raise_for_status(response)
            payload = response.json()
            for message in payload.get("messages") or ():
                ident = message.get("id")
                if isinstance(ident, str):
                    yield ident
            page_token = payload.get("nextPageToken")
            if not page_token:
                return

    async def get_message_raw(
        self,
        *,
        access_token: str,
        message_id: str,
    ) -> dict[str, Any]:
        """Fetch one message in ``format=raw`` and return the JSON payload.

        Args:
            access_token: Bearer token.
            message_id: Gmail message id.

        Returns:
            Decoded JSON body.

        Raises:
            GmailApiError: Non-2xx response after retries.
        """
        response = await self._get(
            f"/messages/{message_id}",
            access_token,
            {"format": "raw"},
        )
        self._raise_for_status(response)
        return response.json()  # type: ignore[no-any-return]

    async def get_profile_history_id(self, *, access_token: str) -> int:
        """Return the mailbox's current ``historyId`` watermark.

        Called after a successful ingest run to advance
        :attr:`SyncCursor.history_id` when the history endpoint reported
        an older value.

        Args:
            access_token: Bearer token.

        Returns:
            The current ``historyId`` as an int.
        """
        response = await self._get("/profile", access_token, {})
        self._raise_for_status(response)
        return int(response.json()["historyId"])

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.5, max=8.0),
        retry=retry_if_exception_type(QuotaExceededError),
    )
    async def _get(
        self,
        path: str,
        access_token: str,
        params: dict[str, Any],
    ) -> httpx.Response:
        """Issue a rate-limited GET with a tenacity retry on 429.

        Args:
            path: API path relative to :data:`API_ROOT`.
            access_token: Bearer token.
            params: Query string parameters.

        Returns:
            The :class:`httpx.Response`; the caller inspects status.

        Raises:
            QuotaExceededError: When Gmail responds 429 (retried up to
                4 times before propagating to the caller).
        """
        await self._bucket.acquire(1.0)
        response = await self._client.get(
            f"{API_ROOT}{path}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )
        if response.status_code == 429:
            raise QuotaExceededError("Gmail returned 429 — backing off")
        if 500 <= response.status_code < 600:
            raise QuotaExceededError(f"Gmail 5xx: {response.status_code}")
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Translate non-2xx responses into :class:`GmailApiError`.

        Args:
            response: Response to inspect.

        Raises:
            GmailApiError: When ``response.status_code`` is >= 300.
        """
        if response.status_code >= 300:
            raise GmailApiError(
                f"Gmail API error {response.status_code}: {response.text[:200]}",
            )
