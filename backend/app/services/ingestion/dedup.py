"""Idempotency ledger for the ingestion pipeline (plan §20.1).

Two layers:

1. ``emails(account_id, gmail_message_id)`` UNIQUE index — enforced by
   the database. We rely on SQLAlchemy's ``IntegrityError`` to catch
   the race where two workers ingest the same message.
2. Content-hash guard — the SHA-256 over
   ``(subject, from, internal_date, snippet)`` is compared before the
   INSERT so re-running a stage does not even attempt the insert when
   nothing about the message has changed.

This module is listed in §20.1 as one of the five 100%-coverage targets;
tests in :mod:`backend.tests.unit.test_dedup` walk every branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models import Email

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable, Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.providers import EmailMessage


@dataclass(frozen=True)
class DedupOutcome:
    """Result of running :func:`classify_incoming`.

    Attributes:
        to_insert: Messages that are safe to INSERT.
        duplicates: Messages already present with an identical content hash.
        divergent: Messages present under the same ``gmail_message_id``
            but with a different content hash — these signal a provider
            replay / attacker-controlled tampering and are logged, not
            mutated.
    """

    to_insert: tuple[EmailMessage, ...]
    duplicates: tuple[EmailMessage, ...]
    divergent: tuple[EmailMessage, ...]


async def existing_message_hashes(
    session: AsyncSession,
    *,
    account_id: UUID,
    message_ids: Sequence[str],
) -> dict[str, bytes]:
    """Return a ``{gmail_message_id: content_hash}`` map for already-ingested rows.

    Args:
        session: Open async session.
        account_id: ``connected_accounts.id``.
        message_ids: Provider-scoped message ids to look up.

    Returns:
        Mapping keyed by ``gmail_message_id``; absent ids are not present
        in the result.
    """
    if not message_ids:
        return {}
    stmt = select(Email.gmail_message_id, Email.content_hash).where(
        Email.account_id == account_id,
        Email.gmail_message_id.in_(list(message_ids)),
    )
    rows = (await session.execute(stmt)).all()
    return {row[0]: bytes(row[1]) for row in rows}


def classify_incoming(
    messages: Iterable[EmailMessage],
    *,
    known_hashes: dict[str, bytes],
) -> DedupOutcome:
    """Split an incoming batch into insert / duplicate / divergent buckets.

    Args:
        messages: Parsed :class:`EmailMessage` values from the provider.
        known_hashes: Output of :func:`existing_message_hashes`.

    Returns:
        A :class:`DedupOutcome` classifying every message in ``messages``.
    """
    to_insert: list[EmailMessage] = []
    duplicates: list[EmailMessage] = []
    divergent: list[EmailMessage] = []
    seen_this_batch: dict[str, bytes] = {}
    for msg in messages:
        existing = known_hashes.get(msg.message_id)
        batch = seen_this_batch.get(msg.message_id)
        if existing is None and batch is None:
            to_insert.append(msg)
            seen_this_batch[msg.message_id] = bytes(msg.content_hash)
        elif existing == bytes(msg.content_hash) or batch == bytes(msg.content_hash):
            duplicates.append(msg)
        else:
            divergent.append(msg)
    return DedupOutcome(
        to_insert=tuple(to_insert),
        duplicates=tuple(duplicates),
        divergent=tuple(divergent),
    )
