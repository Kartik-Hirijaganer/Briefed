"""Gmail implementation of :class:`MailboxProvider` (plan §19.6).

Composes :class:`app.services.gmail.client.GmailClient` with the parser
in :mod:`app.services.gmail.parser` so the ingestion pipeline never
touches raw Gmail JSON.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.core.app_config import get_app_config
from app.core.errors import StaleCursorError
from app.domain.providers import (
    MailboxProvider,
    MarkReadFailure,
    MarkReadResult,
    MessageId,
    ProviderCredentials,
    RawMessage,
    SyncCursor,
)
from app.services.email_labels import UNREAD_LABEL, has_unread_label
from app.services.gmail.client import GmailApiError, GmailClient
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
        bootstrap_lookback_days: int | None = None,
        unread_only: bool | None = None,
    ) -> None:
        """Store collaborators.

        Args:
            client: Live :class:`GmailClient`.
            http_client: The underlying :class:`httpx.AsyncClient` — used
                for the /revoke call on account disconnect.
            bootstrap_lookback_days: Number of days to scan on a stale
                cursor. Plan §19.15 caps this at 14.
            unread_only: Whether bootstrap scans should include only
                Gmail messages still bearing ``UNREAD``.
        """
        scan_config = get_app_config().scan
        self._client = client
        self._http = http_client
        self.bootstrap_lookback_days = (
            bootstrap_lookback_days
            if bootstrap_lookback_days is not None
            else scan_config.lookback_days
        )
        self.unread_only = unread_only if unread_only is not None else scan_config.unread_only

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
                if self.unread_only:
                    history_ids = await self._filter_unread_history_ids(
                        credentials=credentials,
                        message_ids=history_ids,
                    )
                return history_ids, cursor.model_copy(
                    update={"history_id": next_history, "stale": False},
                )
            except StaleCursorError:
                pass

        query_parts = [f"newer_than:{self.bootstrap_lookback_days}d"]
        if self.unread_only:
            query_parts.insert(0, "is:unread")
        query = " ".join(query_parts)
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
            except GmailApiError as exc:
                if exc.status_code == 404:
                    continue
                raise
            results.append(raw_from_gmail_full(payload))
        return results

    async def mark_read(
        self,
        credentials: ProviderCredentials,
        message_ids: list[MessageId],
    ) -> MarkReadResult:
        """Remove Gmail's ``UNREAD`` label from messages.

        Args:
            credentials: Decrypted OAuth credentials with ``gmail.modify``.
            message_ids: Gmail message ids to mark read.

        Returns:
            Provider-level successes and failures. A message already
            lacking ``UNREAD`` is considered successfully processed by
            Gmail's idempotent label mutation.
        """
        unique_ids = tuple(dict.fromkeys(message_ids))
        if not unique_ids:
            return MarkReadResult()

        marked: list[MessageId] = []
        failed: list[MarkReadFailure] = []
        for batch in _chunks(unique_ids, size=1000):
            try:
                await self._client.batch_modify_messages(
                    access_token=credentials.access_token,
                    message_ids=batch,
                    remove_label_ids=(UNREAD_LABEL,),
                )
                marked.extend(batch)
            except GmailApiError as exc:
                if exc.status_code in {401, 403}:
                    failed.extend(_failures(batch, str(exc)))
                    continue
                isolated = await self._mark_read_one_by_one(
                    credentials=credentials,
                    message_ids=batch,
                )
                marked.extend(isolated.marked)
                failed.extend(isolated.failed)
        return MarkReadResult(marked=tuple(marked), failed=tuple(failed))

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

    async def _filter_unread_history_ids(
        self,
        *,
        credentials: ProviderCredentials,
        message_ids: list[MessageId],
    ) -> list[MessageId]:
        """Keep history-added messages that still carry ``UNREAD``.

        Args:
            credentials: Decrypted OAuth credentials.
            message_ids: Candidate ids returned by ``users.history.list``.

        Returns:
            Candidate ids whose live labels still include ``UNREAD``.
        """
        unread_ids: list[MessageId] = []
        for message_id in message_ids:
            try:
                labels = await self._client.get_message_labels(
                    access_token=credentials.access_token,
                    message_id=message_id,
                )
            except GmailApiError as exc:
                if exc.status_code == 404:
                    continue
                raise
            if has_unread_label(labels):
                unread_ids.append(message_id)
        return unread_ids

    async def _mark_read_one_by_one(
        self,
        *,
        credentials: ProviderCredentials,
        message_ids: tuple[MessageId, ...],
    ) -> MarkReadResult:
        """Retry a failed Gmail batch as singleton batchModify calls.

        Args:
            credentials: Decrypted OAuth credentials.
            message_ids: Failed batch ids to isolate.

        Returns:
            Provider-level successes and failures after singleton retries.
        """
        marked: list[MessageId] = []
        failed: list[MarkReadFailure] = []
        for message_id in message_ids:
            try:
                await self._client.batch_modify_messages(
                    access_token=credentials.access_token,
                    message_ids=(message_id,),
                    remove_label_ids=(UNREAD_LABEL,),
                )
                marked.append(message_id)
            except GmailApiError as exc:
                failed.append(MarkReadFailure(message_id=message_id, reason=str(exc)))
        return MarkReadResult(marked=tuple(marked), failed=tuple(failed))


def _chunks(
    values: tuple[MessageId, ...],
    *,
    size: int,
) -> tuple[tuple[MessageId, ...], ...]:
    """Split message ids into Gmail batchModify chunks.

    Args:
        values: Message ids to split.
        size: Maximum chunk size.

    Returns:
        Tuple of chunks preserving input order.
    """
    return tuple(values[index : index + size] for index in range(0, len(values), size))


def _failures(
    message_ids: tuple[MessageId, ...],
    reason: str,
) -> tuple[MarkReadFailure, ...]:
    """Return identical failure records for message ids.

    Args:
        message_ids: Provider ids that failed.
        reason: Failure reason.

    Returns:
        Provider failure models.
    """
    return tuple(
        MarkReadFailure(message_id=message_id, reason=reason) for message_id in message_ids
    )
