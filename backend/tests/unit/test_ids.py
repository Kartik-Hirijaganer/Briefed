"""Tests for :mod:`app.core.ids`."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.core.ids import content_hash, idempotency_key, new_uuid, sha256_bytes


def test_new_uuid_is_v4() -> None:
    value = new_uuid()
    assert isinstance(value, UUID)
    assert value.version == 4


def test_sha256_bytes_is_deterministic() -> None:
    d1 = sha256_bytes(b"a", b"b", b"c")
    d2 = sha256_bytes(b"abc")
    assert d1 == d2
    assert len(d1) == 32


def test_content_hash_changes_on_any_input_change() -> None:
    a = content_hash(subject="x", from_addr="x@y", internal_date_ms=1, snippet="s")
    b = content_hash(subject="y", from_addr="x@y", internal_date_ms=1, snippet="s")
    assert a != b


def test_idempotency_key_is_hex_sha256() -> None:
    key = idempotency_key(run_id=uuid4(), stage="ingest", entity_id="m1")
    assert len(key) == 64
    assert int(key, 16) >= 0
