"""100%-coverage tests for ingestion dedup (plan §20.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.domain.providers import EmailAddress, EmailMessage
from app.services.ingestion.dedup import classify_incoming, existing_message_hashes


def _make_message(message_id: str, *, digest: bytes) -> EmailMessage:
    return EmailMessage(
        account_id=uuid4(),
        message_id=message_id,
        thread_id="t",
        internal_date=datetime.now(tz=UTC),
        from_addr=EmailAddress(email="a@example.com"),
        subject="s",
        snippet="",
        content_hash=digest,
        size_bytes=10,
    )


def test_empty_input_returns_empty() -> None:
    outcome = classify_incoming([], known_hashes={})
    assert outcome.to_insert == ()
    assert outcome.duplicates == ()
    assert outcome.divergent == ()


def test_first_time_message_is_insertable() -> None:
    msg = _make_message("m1", digest=b"h" * 32)
    outcome = classify_incoming([msg], known_hashes={})
    assert outcome.to_insert == (msg,)


def test_duplicate_hash_goes_to_duplicates_bucket() -> None:
    digest = b"h" * 32
    msg = _make_message("m1", digest=digest)
    outcome = classify_incoming([msg], known_hashes={"m1": digest})
    assert outcome.duplicates == (msg,)
    assert outcome.to_insert == ()


def test_divergent_hash_goes_to_divergent_bucket() -> None:
    msg = _make_message("m1", digest=b"h" * 32)
    outcome = classify_incoming([msg], known_hashes={"m1": b"x" * 32})
    assert outcome.divergent == (msg,)
    assert outcome.to_insert == ()


def test_batch_level_dedup_collapses_same_id_twice() -> None:
    digest = b"h" * 32
    msg1 = _make_message("m1", digest=digest)
    msg2 = _make_message("m1", digest=digest)
    outcome = classify_incoming([msg1, msg2], known_hashes={})
    assert outcome.to_insert == (msg1,)
    assert outcome.duplicates == (msg2,)


async def test_existing_message_hashes_empty_id_list_returns_empty() -> None:
    # No session work happens when message_ids is empty.
    result = await existing_message_hashes(
        session=None,  # type: ignore[arg-type]
        account_id=uuid4(),
        message_ids=[],
    )
    assert result == {}
