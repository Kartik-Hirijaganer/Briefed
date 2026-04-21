"""Ingest SQS-handler (plan §14 Phase 1).

One invocation processes one :class:`IngestMessage` — fetches the
account's decrypted OAuth credentials, runs the ingestion pipeline, and
hands over the stats for the digest_runs row.

Retry semantics:

* ``QuotaExceededError`` from Gmail → raise so SQS re-delivers.
* ``StaleCursorError`` → handled inside the provider; never bubbles up.
* Everything else → propagates; the Lambda dispatcher records a
  ``batchItemFailures`` entry so SQS re-delivers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.core.security import EncryptedBlob, EnvelopeCipher, token_context
from app.db.models import OAuthToken
from app.domain.providers import ProviderCredentials
from app.services.ingestion.pipeline import IngestStats, run_ingest

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.providers import MailboxProvider
    from app.services.ingestion.storage import ObjectStore
    from app.workers.messages import IngestMessage


logger = get_logger(__name__)


@dataclass
class IngestDeps:
    """Collaborators the ingest handler needs.

    Attributes:
        session: Open :class:`AsyncSession`.
        provider: :class:`MailboxProvider` implementation (Gmail in 1.0.0).
        cipher: :class:`EnvelopeCipher` for unwrapping refresh/access tokens.
        content_cipher: Optional content-at-rest cipher for body excerpts.
        raw_storage: Optional S3 client for raw MIME uploads.
        raw_bucket: Bucket name when raw MIME is enabled.
    """

    session: AsyncSession
    provider: MailboxProvider
    cipher: EnvelopeCipher
    content_cipher: EnvelopeCipher | None = None
    raw_storage: ObjectStore | None = None
    raw_bucket: str | None = None


async def handle_ingest(
    message: IngestMessage,
    *,
    deps: IngestDeps,
) -> IngestStats:
    """Process one :class:`IngestMessage`.

    Args:
        message: The validated payload.
        deps: :class:`IngestDeps`.

    Returns:
        :class:`IngestStats` summarizing the run.

    Raises:
        LookupError: When the account no longer has OAuth credentials.
    """
    tokens = (
        (
            await deps.session.execute(
                select(OAuthToken).where(OAuthToken.account_id == message.account_id),
            )
        )
        .scalars()
        .first()
    )
    if tokens is None:
        raise LookupError(f"no OAuthToken for account {message.account_id}")

    account_ctx = str(message.account_id)
    access_plain = deps.cipher.decrypt(
        _blob(tokens.access_token_ct),
        token_context(account_id=account_ctx, purpose="access_token"),
    )
    refresh_plain = deps.cipher.decrypt(
        _blob(tokens.refresh_token_ct),
        token_context(account_id=account_ctx, purpose="refresh_token"),
    )

    credentials = ProviderCredentials(
        account_id=message.account_id,
        access_token=access_plain.decode("utf-8"),
        refresh_token=refresh_plain.decode("utf-8"),
        scope=tuple(tokens.scope),
        expires_at=tokens.expires_at,
    )

    started = utcnow()
    stats = await run_ingest(
        session=deps.session,
        account_id=message.account_id,
        provider=deps.provider,
        credentials=credentials,
        raw_storage=deps.raw_storage,
        raw_bucket=deps.raw_bucket,
        store_raw_mime=message.store_raw_mime,
        content_cipher=deps.content_cipher,
    )
    logger.info(
        "ingest.handler.completed",
        account_id=account_ctx,
        run_id=str(message.run_id) if message.run_id else None,
        new=stats.new,
        duplicates=stats.duplicates,
        divergent=stats.divergent,
        elapsed_ms=int((utcnow() - started).total_seconds() * 1000),
    )
    return stats


def _blob(ciphertext: bytes) -> EncryptedBlob:
    """Coerce a raw ``BYTEA`` column into :class:`EncryptedBlob`.

    Args:
        ciphertext: The raw bytes loaded from the DB.

    Returns:
        An :class:`EncryptedBlob` suitable for
        :meth:`EnvelopeCipher.decrypt`.
    """
    return EncryptedBlob(ciphertext=bytes(ciphertext))
