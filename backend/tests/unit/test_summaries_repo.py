"""Unit tests for :class:`SummariesRepo` (plan §14 Phase 3, §20.10).

Covers:

* encrypt-on-write / decrypt-on-read round-trip with a fake KMS;
* pass-through mode (cipher=None) used by unit tests;
* per-email vs cluster guardrails (type mismatch rejects the decrypt).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.core.security import EnvelopeCipher
from app.db.models import (
    ConnectedAccount,
    Email,
    TechNewsCluster,
    User,
)
from app.services.summarization import (
    SummariesRepo,
    SummaryEmailWrite,
    SummaryTechNewsWrite,
)


class _FakeKms:
    def __init__(self) -> None:
        self._master = b"K" * 32

    def encrypt(self, **kwargs: Any) -> dict[str, Any]:
        pt = kwargs["Plaintext"]
        wrapped = bytes(b ^ m for b, m in zip(pt, self._master, strict=True))
        return {"CiphertextBlob": len(pt).to_bytes(2, "big") + wrapped}

    def decrypt(self, **kwargs: Any) -> dict[str, Any]:
        blob = kwargs["CiphertextBlob"]
        length = int.from_bytes(blob[:2], "big")
        wrapped = blob[2:]
        pt = bytes(b ^ m for b, m in zip(wrapped, self._master, strict=True))
        assert len(pt) == length
        return {"Plaintext": pt}


async def _seed_email(session, *, user: User) -> Email:
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="mbox@example.com",
        status="active",
    )
    session.add(account)
    await session.flush()
    email = Email(
        account_id=account.id,
        gmail_message_id=str(uuid4()),
        thread_id="t-1",
        internal_date=datetime.now(tz=UTC),
        from_addr="a@example.com",
        to_addrs=[],
        cc_addrs=[],
        subject="subject",
        snippet="",
        labels=[],
        content_hash=hashlib.sha256(b"x").digest(),
    )
    session.add(email)
    await session.flush()
    return email


@pytest.mark.asyncio
async def test_email_summary_encrypt_roundtrip(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    email = await _seed_email(test_session, user=user)

    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    repo = SummariesRepo(cipher=cipher)

    row = await repo.upsert_email(
        test_session,
        SummaryEmailWrite(
            email_id=email.id,
            user_id=user.id,
            prompt_version_id=None,
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            body_md="Cofounder wants a call.",
            entities=("ACME", "Friday"),
            confidence=Decimal("0.900"),
            cache_hit=False,
            batch_id=None,
        ),
    )
    assert row.body_md_ct != b"Cofounder wants a call."
    assert row.entities_ct is not None

    body = repo.decrypt_email_body(row=row, user_id=user.id)
    entities = repo.decrypt_email_entities(row=row, user_id=user.id)
    assert body == "Cofounder wants a call."
    assert entities == ("ACME", "Friday")


@pytest.mark.asyncio
async def test_cluster_summary_encrypt_roundtrip(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()

    cluster = TechNewsCluster(
        user_id=user.id,
        run_id=None,
        cluster_key="llm-research",
        topic_hint="",
        member_count=2,
    )
    test_session.add(cluster)
    await test_session.flush()

    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    repo = SummariesRepo(cipher=cipher)

    row = await repo.upsert_tech_news_cluster(
        test_session,
        SummaryTechNewsWrite(
            cluster_id=cluster.id,
            user_id=user.id,
            prompt_version_id=None,
            model="gemini-1.5-flash",
            tokens_in=30,
            tokens_out=20,
            body_md="**Headline**\n- bullet",
            sources=("Subject A", "Subject B"),
            confidence=Decimal("0.800"),
            cache_hit=True,
            batch_id="batch-1",
        ),
    )
    assert row.cache_hit is True
    body = repo.decrypt_cluster_body(row=row, user_id=user.id)
    sources = repo.decrypt_cluster_sources(row=row, user_id=user.id)
    assert body.startswith("**Headline**")
    assert sources == ("Subject A", "Subject B")


@pytest.mark.asyncio
async def test_decrypt_rejects_wrong_kind(test_session) -> None:
    repo = SummariesRepo(cipher=None)
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    email = await _seed_email(test_session, user=user)
    row = await repo.upsert_email(
        test_session,
        SummaryEmailWrite(
            email_id=email.id,
            user_id=user.id,
            prompt_version_id=None,
            model="gemini-1.5-flash",
            tokens_in=1,
            tokens_out=1,
            body_md="x",
            entities=(),
            confidence=Decimal("0.5"),
            cache_hit=False,
            batch_id=None,
        ),
    )
    with pytest.raises(ValueError):
        repo.decrypt_cluster_body(row=row, user_id=user.id)
