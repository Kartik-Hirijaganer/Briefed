"""Ingestion pipeline orchestration (plan §7).

High-level flow per run:

1. Fetch the account's current :class:`SyncCursor`.
2. Ask the :class:`MailboxProvider` for new ids + the advanced cursor.
3. Batch-fetch :class:`RawMessage` payloads.
4. Parse each into a :class:`EmailMessage` + :class:`EmailBody` pair.
5. Dedup via :func:`app.services.ingestion.dedup.classify_incoming`.
6. Insert ``emails`` + ``email_content_blobs`` rows in one transaction.
7. Optionally upload raw MIME to S3.
8. Persist the advanced cursor.

Errors are surfaced as exceptions so the SQS handler can decide whether
to retry (QuotaExceededError) or park on DLQ (ProviderError).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import ConnectedAccount, Email, EmailContentBlob, SyncCursor
from app.domain.providers import SyncCursor as DomainCursor
from app.services.gmail.parser import parse_message
from app.services.ingestion.content import encrypt_excerpt
from app.services.ingestion.dedup import (
    classify_incoming,
    existing_message_hashes,
)
from app.services.ingestion.storage import maybe_store_raw_mime

if TYPE_CHECKING:  # pragma: no cover
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher
    from app.domain.providers import (
        MailboxProvider,
        ProviderCredentials,
    )
    from app.services.ingestion.storage import ObjectStore


logger = get_logger(__name__)


@dataclass(frozen=True)
class IngestStats:
    """Summary of a single ingestion invocation.

    Attributes:
        new: Rows inserted.
        duplicates: Rows already present with matching hash.
        divergent: Rows flagged for out-of-band review.
        raw_uploaded: Count of raw-MIME uploads (0 when opt-out).
        cursor_stale: True if the provider reported a stale cursor and we
            ran the bounded fallback scan.
    """

    new: int
    duplicates: int
    divergent: int
    raw_uploaded: int
    cursor_stale: bool


async def run_ingest(
    *,
    session: AsyncSession,
    account_id: UUID,
    provider: MailboxProvider,
    credentials: ProviderCredentials,
    raw_storage: ObjectStore | None = None,
    raw_bucket: str | None = None,
    store_raw_mime: bool = False,
    content_cipher: EnvelopeCipher | None = None,
) -> IngestStats:
    """Run the ingestion pipeline for a single connected account.

    Args:
        session: Open async session (caller owns commit boundary).
        account_id: Target account.
        provider: :class:`MailboxProvider` implementation.
        credentials: Decrypted OAuth credentials.
        raw_storage: Optional :class:`ObjectStore` for raw MIME uploads.
        raw_bucket: Bucket to upload to when ``store_raw_mime`` is True.
        store_raw_mime: Per-user toggle.
        content_cipher: Optional content-at-rest cipher for body excerpts.

    Returns:
        An :class:`IngestStats` summary.
    """
    cursor_row = await _get_or_create_cursor(session, account_id=account_id)
    account = await session.get(ConnectedAccount, account_id)
    if account is None:
        raise LookupError(f"unknown connected_account {account_id}")
    cursor = _cursor_to_domain(cursor_row)

    new_ids, advanced_cursor = await provider.list_new_ids(credentials, cursor)
    if not new_ids:
        await _persist_cursor(session, cursor_row, advanced_cursor, touched=False)
        return IngestStats(0, 0, 0, 0, advanced_cursor.stale)

    raw_messages = await provider.get_messages(credentials, new_ids)
    parsed = [parse_message(raw, account_id=account_id) for raw in raw_messages]
    metadatas = [meta for meta, _ in parsed]

    known = await existing_message_hashes(
        session,
        account_id=account_id,
        message_ids=[meta.message_id for meta in metadatas],
    )
    outcome = classify_incoming(metadatas, known_hashes=known)

    raw_uploaded = 0
    for raw, (meta, body) in zip(raw_messages, parsed, strict=True):
        if meta not in outcome.to_insert:
            continue
        email = Email(
            account_id=account_id,
            gmail_message_id=meta.message_id,
            thread_id=meta.thread_id,
            internal_date=meta.internal_date,
            from_addr=meta.from_addr.email,
            to_addrs=[addr.email for addr in meta.to_addrs],
            cc_addrs=[addr.email for addr in meta.cc_addrs],
            subject=meta.subject,
            snippet=meta.snippet,
            labels=list(meta.labels),
            list_unsubscribe=(
                meta.list_unsubscribe.model_dump() if meta.list_unsubscribe else None
            ),
            content_hash=bytes(meta.content_hash),
            size_bytes=meta.size_bytes,
        )
        email.body = EmailContentBlob(
            message_id=email.id,
            storage_backend="pg",
            plain_text_excerpt_ct=encrypt_excerpt(
                body.plain_text_excerpt,
                message_id=email.id,
                user_id=account.user_id,
                cipher=content_cipher,
            ),
            plain_text_dek_wrapped=None,
            quoted_text_removed=body.quoted_text_removed,
            language=body.language,
            size_bytes=body.size_bytes,
        )
        session.add(email)
        if raw_storage is not None and raw_bucket is not None:
            stored = maybe_store_raw_mime(
                store=raw_storage,
                bucket=raw_bucket,
                account_id=account_id,
                message_id=meta.message_id,
                raw_mime=raw.raw_mime,
                enabled=store_raw_mime,
            )
            if stored is not None:
                email.raw_s3_key = stored.key
                raw_uploaded += 1

    await session.flush()
    await _persist_cursor(session, cursor_row, advanced_cursor, touched=True)

    logger.info(
        "ingest.completed",
        account_id=str(account_id),
        new=len(outcome.to_insert),
        duplicates=len(outcome.duplicates),
        divergent=len(outcome.divergent),
        raw_uploaded=raw_uploaded,
        stale_cursor=advanced_cursor.stale,
    )
    return IngestStats(
        new=len(outcome.to_insert),
        duplicates=len(outcome.duplicates),
        divergent=len(outcome.divergent),
        raw_uploaded=raw_uploaded,
        cursor_stale=advanced_cursor.stale,
    )


async def _get_or_create_cursor(
    session: AsyncSession,
    *,
    account_id: UUID,
) -> SyncCursor:
    """Return the account's cursor row, creating a fresh one on first run.

    Args:
        session: Open async session.
        account_id: Target account.

    Returns:
        A SQLAlchemy :class:`SyncCursor` row attached to ``session``.

    Raises:
        LookupError: If ``account_id`` does not exist.
    """
    cursor = await session.get(SyncCursor, account_id)
    if cursor is None:
        account = await session.get(ConnectedAccount, account_id)
        if account is None:
            raise LookupError(f"unknown connected_account {account_id}")
        cursor = SyncCursor(account_id=account_id, history_id=None, stale=False)
        session.add(cursor)
        await session.flush()
    return cursor


def _cursor_to_domain(row: SyncCursor) -> DomainCursor:
    """Convert an ORM cursor into the Pydantic :class:`domain.SyncCursor`."""
    return DomainCursor(
        account_id=row.account_id,
        history_id=row.history_id,
        last_full_sync_at=row.last_full_sync_at,
        last_incremental_at=row.last_incremental_at,
        stale=row.stale,
    )


async def _persist_cursor(
    session: AsyncSession,
    row: SyncCursor,
    advanced: DomainCursor,
    *,
    touched: bool,
) -> None:
    """Write the advanced cursor back into the DB row.

    Args:
        session: Open async session.
        row: The ORM row loaded by :func:`_get_or_create_cursor`.
        advanced: The domain-level cursor returned by the provider.
        touched: True when at least one message was processed in this
            run; drives whether ``last_full_sync_at`` / ``last_incremental_at``
            advance.
    """
    row.history_id = advanced.history_id
    row.stale = advanced.stale
    now = utcnow()
    if touched:
        row.last_incremental_at = now
        if advanced.stale:
            row.last_full_sync_at = now
    await session.flush()


__all__ = ["IngestStats", "run_ingest"]
