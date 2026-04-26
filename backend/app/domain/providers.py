"""Mailbox + identity seams (plan §19.6, §19.3).

:class:`MailboxProvider` is the protocol every inbox source implements. Release
1.0.0 ships :class:`app.services.gmail.provider.GmailProvider` only; Outlook
and IMAP adapters slot in later without touching the ingestion pipeline.

Pydantic types are used for every value object that crosses a boundary so the
worker-handlers, the API layer, and tests all validate the same shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

MessageId = str
"""Opaque provider-scoped identifier for a single message.

Gmail returns a 16-char hex string; Outlook a base64 blob. Callers never
parse these — they pass them back to the provider on subsequent calls.
"""


class ProviderCredentials(BaseModel):
    """Decrypted OAuth credentials ready for use by a provider.

    Attributes:
        account_id: Database ``connected_accounts.id`` for the account.
        access_token: Short-lived token injected into provider requests.
        refresh_token: Long-lived token used to mint new access tokens.
        scope: Granted scope strings (space-separated in OAuth payloads).
        expires_at: UTC instant the access_token stops being valid.
    """

    model_config = ConfigDict(frozen=True)

    account_id: UUID = Field(..., description="connected_accounts.id")
    access_token: str = Field(..., description="Short-lived OAuth access token.")
    refresh_token: str = Field(..., description="Refresh token used to rotate access.")
    scope: tuple[str, ...] = Field(default=(), description="Granted scope identifiers.")
    expires_at: datetime = Field(..., description="UTC expiry of the access token.")


class SyncCursor(BaseModel):
    """Opaque, provider-specific incremental-sync cursor.

    For Gmail this wraps the ``historyId`` returned by ``users.history.list``;
    stale cursors (older than Gmail's ~7-day history retention) surface as
    :attr:`stale`. Callers treat the cursor as opaque and pass it back.

    Attributes:
        account_id: ``connected_accounts.id`` the cursor belongs to.
        history_id: Latest observed Gmail ``historyId`` (or opaque provider
            marker).
        last_incremental_at: UTC timestamp of the most recent successful
            incremental run. ``None`` when the cursor has never advanced.
        last_full_sync_at: UTC timestamp of the most recent bounded full
            sync. ``None`` until the first bootstrap completes.
        stale: True when the provider rejected the cursor; callers must run
            a bounded-lookback full sync instead.
    """

    model_config = ConfigDict(frozen=True)

    account_id: UUID
    history_id: int | None = Field(default=None, description="Latest historyId.")
    last_incremental_at: datetime | None = Field(default=None)
    last_full_sync_at: datetime | None = Field(default=None)
    stale: bool = Field(default=False, description="Cursor needs full-sync fallback.")


class EmailAddress(BaseModel):
    """A single parsed address with optional display name.

    Attributes:
        email: RFC-5322-validated address.
        name: Optional display name (``None`` when the header lacked one).
    """

    model_config = ConfigDict(frozen=True)

    email: EmailStr
    name: str | None = Field(default=None, description="Display name if present.")


class UnsubscribeInfo(BaseModel):
    """Normalized ``List-Unsubscribe`` header.

    Gmail returns the raw header; we split it into its HTTP and mailto
    components (plan §5 hygiene pipeline consumes both). One-click
    unsubscribe per RFC-8058 is signaled by :attr:`one_click`.

    Attributes:
        http_urls: Well-formed ``https://`` URLs the recipient can GET/POST.
        mailto: Optional ``mailto:`` destination.
        one_click: True when the ``List-Unsubscribe-Post: List-Unsubscribe=One-Click``
            header pair was present.
    """

    model_config = ConfigDict(frozen=True)

    http_urls: tuple[str, ...] = Field(default=())
    mailto: str | None = Field(default=None)
    one_click: bool = Field(default=False)


class EmailMessage(BaseModel):
    """Boundary-validated email metadata (downstream never sees raw Gmail JSON).

    This is the Pydantic value object produced by the Gmail parser (plan
    §8 `emails` row). Bodies are handled separately via
    :class:`email_content_blobs` and never land in this object to keep row
    size small.

    Attributes:
        provider_id: Provider slug (``"gmail"`` today).
        account_id: ``connected_accounts.id``.
        message_id: Provider-scoped message identifier.
        thread_id: Provider-scoped thread identifier.
        internal_date: Provider-reported send time (UTC).
        from_addr: Parsed ``From`` header.
        to_addrs: Parsed ``To`` headers (possibly empty).
        cc_addrs: Parsed ``Cc`` headers (possibly empty).
        subject: Decoded, RFC-2047-normalized subject.
        snippet: Provider-produced short plaintext preview.
        labels: Labels / folders assigned to the message.
        list_unsubscribe: Normalized ``List-Unsubscribe`` header if any.
        content_hash: SHA-256 over ``(subject, from_addr, internal_date,
            snippet)`` used to short-circuit re-ingest.
        size_bytes: Raw MIME byte length reported by the provider.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: Literal["gmail"] = Field(default="gmail")
    account_id: UUID
    message_id: MessageId
    thread_id: str
    internal_date: datetime
    from_addr: EmailAddress
    to_addrs: tuple[EmailAddress, ...] = Field(default=())
    cc_addrs: tuple[EmailAddress, ...] = Field(default=())
    subject: str
    snippet: str = Field(default="")
    labels: tuple[str, ...] = Field(default=())
    list_unsubscribe: UnsubscribeInfo | None = Field(default=None)
    content_hash: bytes = Field(..., description="32-byte SHA-256 digest.")
    size_bytes: int = Field(default=0, ge=0)


class EmailBody(BaseModel):
    """Parsed, sanitized email body companion to :class:`EmailMessage`.

    Separated so that ingestion can persist bodies to
    ``email_content_blobs`` while ``emails`` stays slim.

    Attributes:
        message_id: Provider-scoped message id (matches EmailMessage).
        plain_text_excerpt: First N chars of decoded text/plain (quoted
            tails trimmed when possible).
        html_sanitized: Sanitized HTML for rendering. ``None`` when the
            message had no HTML part.
        quoted_text_removed: True when the parser trimmed a quoted reply.
        language: Detected or provider-declared language code.
        size_bytes: Length of the raw body before excerpting.
    """

    model_config = ConfigDict(frozen=True)

    message_id: MessageId
    plain_text_excerpt: str = Field(default="")
    html_sanitized: str | None = Field(default=None)
    quoted_text_removed: bool = Field(default=False)
    language: str | None = Field(default=None)
    size_bytes: int = Field(default=0, ge=0)


class RawMessage(BaseModel):
    """Provider-returned raw message payload (pre-parse boundary object).

    Callers receive :class:`RawMessage` from the provider and feed it to
    :class:`app.services.gmail.parser.parse_message` which returns
    :class:`EmailMessage` + :class:`EmailBody`.

    Attributes:
        message_id: Provider id of this message.
        thread_id: Thread this message belongs to.
        internal_date_ms: Unix epoch ms reported by the provider.
        size_bytes: Declared size of the raw MIME.
        raw_mime: The raw ``message/rfc822`` bytes (may be omitted when the
            provider returned only ``metadata`` format).
        label_ids: Labels as returned by the provider.
        header_map: Minimal pre-parsed headers — we always keep
            ``Subject``, ``From``, ``To``, ``Cc``, ``List-Unsubscribe``,
            ``List-Unsubscribe-Post``, ``Date``, ``Message-ID``.
        snippet: Provider preview text (if supplied).
    """

    model_config = ConfigDict(frozen=True)

    message_id: MessageId
    thread_id: str
    internal_date_ms: int = Field(..., ge=0)
    size_bytes: int = Field(default=0, ge=0)
    raw_mime: bytes | None = Field(default=None)
    label_ids: tuple[str, ...] = Field(default=())
    header_map: dict[str, str] = Field(default_factory=dict)
    snippet: str = Field(default="")


@runtime_checkable
class MailboxProvider(Protocol):
    """Seam every inbox adapter implements (plan §19.6).

    The ingestion pipeline depends on this interface, not on the concrete
    :class:`app.services.gmail.provider.GmailProvider`. Future
    ``OutlookProvider`` and ``ImapProvider`` slot in without pipeline
    changes.
    """

    kind: Literal["gmail", "outlook", "imap"]

    async def list_new_ids(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> tuple[list[MessageId], SyncCursor]:
        """Enumerate message ids added since ``cursor`` and return an advanced cursor.

        Args:
            credentials: Decrypted OAuth credentials for the account.
            cursor: The last-known sync cursor; may be stale.

        Returns:
            Pair of (new message ids, updated cursor). The returned cursor
            has :attr:`SyncCursor.stale` set to ``True`` when the provider
            refused the cursor and the caller must do a bounded backfill.
        """
        ...

    async def get_messages(
        self,
        credentials: ProviderCredentials,
        ids: list[MessageId],
    ) -> list[RawMessage]:
        """Fetch full payloads for the given message ids.

        Args:
            credentials: Decrypted OAuth credentials.
            ids: Provider-scoped message ids to fetch.

        Returns:
            A list aligned with ``ids``; missing messages (deleted between
            listing and fetch) are silently dropped rather than raising.
        """
        ...

    async def refresh_cursor(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> SyncCursor:
        """Advance ``cursor`` to the provider's latest watermark.

        Called after a successful fetch to persist the new cursor.

        Args:
            credentials: Decrypted OAuth credentials.
            cursor: The cursor as of the most recent ``list_new_ids`` call.

        Returns:
            An advanced, non-stale cursor suitable for persistence.
        """
        ...

    async def revoke(self, credentials: ProviderCredentials) -> None:
        """Revoke the provider-side grant for these credentials.

        Called on account disconnect. Implementations must be idempotent —
        re-revoking a token already revoked upstream must not raise.

        Args:
            credentials: Decrypted OAuth credentials to revoke.
        """
        ...
