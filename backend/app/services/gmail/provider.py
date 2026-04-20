"""Gmail implementation of :class:`MailboxProvider` (plan §19.6).

Composes :class:`app.services.gmail.client.GmailClient` with the parser
in :mod:`app.services.gmail.parser` so the ingestion pipeline never
touches raw Gmail JSON.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.core.errors import StaleCursorError
from app.domain.providers import (
    MailboxProvider,
    MessageId,
    ProviderCredentials,
    RawMessage,
    SyncCursor,
)
from app.services.gmail.client import GmailClient
from app.services.gmail.oauth import revoke_token
from app.services.gmail.parser import raw_from_gmail_full

if TYPE_CHECKING:  # pragma: no cover
    import httpx


class GmailProvider(MailboxProvider):
    """Concrete :class:`MailboxProvider` backed by the Gmail REST API.

    Attributes:
        kind: Always ``"gmail"``.
        bootstrap_lookback_days: Window used on a first-run / stale-cursor
            bootstrap. Mirrors ``settings.ingestion.bootstrap_lookback_days``.
    """

    kind: Literal["gmail", "outlook", "imap"] = "gmail"

    def __init__(
        self,
        *,
        client: GmailClient,
        http_client: httpx.AsyncClient,
        bootstrap_lookback_days: int = 14,
    ) -> None:
        """Store collaborators.

        Args:
            client: Live :class:`GmailClient`.
            http_client: The underlying :class:`httpx.AsyncClient` — used
                for the /revoke call on account disconnect.
            bootstrap_lookback_days: Number of days to scan on a stale
                cursor. Plan §19.15 caps this at 14.
        """
        self._client = client
        self._http = http_client
        self.bootstrap_lookback_days = bootstrap_lookback_days

    async def list_new_ids(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> tuple[list[MessageId], SyncCursor]:
        """Return message ids added since ``cursor`` + the advanced cursor.

        On a ``StaleCursorError`` we fall back to a bounded
        ``messages.list`` scan (``newer_than:{bootstrap_lookback_days}d``)
        and mark the returned cursor as stale so the caller knows to run
        a full sync write-out on :attr:`SyncCursor.last_full_sync_at`.

        Args:
            credentials: Decrypted OAuth credentials.
            cursor: The last-known cursor.

        Returns:
            A pair of (new ids, updated cursor).
        """
        if cursor.history_id and not cursor.stale:
            try:
                added, next_history = await self._client.list_history(
                    access_token=credentials.access_token,
                    start_history_id=cursor.history_id,
                )
                history_ids = [
                    str(entry.get("id"))
                    for entry in added
                    if isinstance(entry, dict) and entry.get("id")
                ]
                return history_ids, cursor.model_copy(
                    update={"history_id": next_history, "stale": False},
                )
            except StaleCursorError:
                pass

        query = f"newer_than:{self.bootstrap_lookback_days}d"
        full_ids: list[MessageId] = []
        async for message_id in self._client.list_messages(
            access_token=credentials.access_token,
            query=query,
        ):
            full_ids.append(message_id)
        watermark = await self._client.get_profile_history_id(
            access_token=credentials.access_token,
        )
        return full_ids, cursor.model_copy(update={"history_id": watermark, "stale": True})

    async def get_messages(
        self,
        credentials: ProviderCredentials,
        ids: list[MessageId],
    ) -> list[RawMessage]:
        """Fetch and decode each message id into a :class:`RawMessage`.

        Args:
            credentials: Decrypted OAuth credentials.
            ids: Message ids to fetch.

        Returns:
            A list of :class:`RawMessage`. Messages that Gmail returns
            404 for (race with user-deletion) are silently skipped.
        """
        results: list[RawMessage] = []
        for message_id in ids:
            try:
                payload = await self._client.get_message_raw(
                    access_token=credentials.access_token,
                    message_id=message_id,
                )
            except Exception:
                continue
            results.append(raw_from_gmail_full(payload))
        return results

    async def refresh_cursor(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> SyncCursor:
        """Advance the cursor to Gmail's current watermark.

        Args:
            credentials: Decrypted OAuth credentials.
            cursor: The cursor as of the most recent fetch.

        Returns:
            A non-stale :class:`SyncCursor` reflecting the live
            ``historyId``.
        """
        watermark = await self._client.get_profile_history_id(
            access_token=credentials.access_token,
        )
        return cursor.model_copy(update={"history_id": watermark, "stale": False})

    async def revoke(self, credentials: ProviderCredentials) -> None:
        """Revoke Google's side of the grant.

        Args:
            credentials: The credentials to revoke.
        """
        await revoke_token(token=credentials.refresh_token, http_client=self._http)
