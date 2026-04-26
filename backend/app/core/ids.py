"""UUID + hashing helpers (plan §8).

Every primary key in the data model is ``gen_random_uuid()`` — a
Postgres-side UUIDv4. Python code that synthesises ids locally (for the
idempotency ledger, for deterministic test fixtures) goes through the
helpers in this module so we only ever call :func:`uuid.uuid4` through
one seam.
"""

from __future__ import annotations

import hashlib
import uuid


def new_uuid() -> uuid.UUID:
    """Return a fresh UUIDv4.

    Wraps :func:`uuid.uuid4` so tests can monkeypatch this single symbol
    when deterministic ids are required.

    Returns:
        A random :class:`uuid.UUID` version 4.
    """
    return uuid.uuid4()


def sha256_bytes(*chunks: bytes) -> bytes:
    """Return the SHA-256 digest of the concatenated chunks.

    Args:
        *chunks: Arbitrary byte strings fed into the hash in order.

    Returns:
        Raw 32-byte digest (suitable for a BYTEA column).
    """
    hasher = hashlib.sha256()
    for chunk in chunks:
        hasher.update(chunk)
    return hasher.digest()


def content_hash(
    *,
    subject: str,
    from_addr: str,
    internal_date_ms: int,
    snippet: str,
) -> bytes:
    """Compute the dedup-guard content hash for an email.

    Plan §8 mandates a content hash beside the
    ``UNIQUE(account_id, gmail_message_id)`` index so that threads with
    re-used message ids (extremely rare, but attacker-controlled in
    principle) still collapse to a single ingested row.

    Args:
        subject: Decoded subject line.
        from_addr: Raw ``From`` header value.
        internal_date_ms: Provider-reported send time (epoch ms).
        snippet: Provider-supplied preview text.

    Returns:
        32-byte SHA-256 digest bound to the input tuple.
    """
    payload = "\n".join(
        (subject, from_addr, str(internal_date_ms), snippet),
    ).encode("utf-8")
    return sha256_bytes(payload)


def idempotency_key(*, run_id: uuid.UUID, stage: str, entity_id: str) -> str:
    """Return the ledger key for (run, stage, entity) idempotency.

    Matches the ``processed_messages.key`` column contract.

    Args:
        run_id: Current digest-run id.
        stage: Pipeline stage slug (``"ingest"``, ``"classify"``, …).
        entity_id: Stable per-stage id (typically the message id).

    Returns:
        Hex-encoded SHA-256 digest suitable for a PRIMARY KEY column.
    """
    payload = f"{run_id.hex}:{stage}:{entity_id}".encode()
    return sha256_bytes(payload).hex()
