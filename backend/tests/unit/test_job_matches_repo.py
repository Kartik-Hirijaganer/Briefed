"""Unit tests for :class:`JobMatchesRepo` (plan §14 Phase 4, §20.10).

Covers:

* encrypt-on-write / decrypt-on-read round-trip with a fake KMS;
* pass-through mode when the cipher is ``None`` (tests only);
* upsert replaces the row in place (one row per email);
* empty plaintext round-trips as empty.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.security import EnvelopeCipher
from app.db.models import ConnectedAccount, Email, JobMatch, User
from app.services.jobs.repository import JobMatchesRepo, JobMatchWrite


class _FakeKms:
    def __init__(self) -> None:
        self._master = b"J" * 32

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
        from_addr="recruiter@example.com",
        to_addrs=[],
        cc_addrs=[],
        subject="Staff Engineer",
        snippet="",
        labels=[],
        content_hash=hashlib.sha256(b"x").digest(),
    )
    session.add(email)
    await session.flush()
    return email


def _payload(
    *,
    email_id,
    user_id,
    match_reason: str = "Fits well",
) -> JobMatchWrite:
    return JobMatchWrite(
        email_id=email_id,
        user_id=user_id,
        title="Staff Backend Engineer",
        company="Acme",
        location="US",
        remote=True,
        comp_min=210_000,
        comp_max=260_000,
        currency="USD",
        comp_phrase="$210k-$260k",
        seniority="staff",
        source_url="https://acme.example/jobs/staff-backend",
        match_score=Decimal("0.880"),
        filter_version=3,
        passed_filter=True,
        prompt_version_id=None,
        model="gemini-1.5-flash",
        tokens_in=120,
        tokens_out=80,
        match_reason=match_reason,
    )


@pytest.mark.asyncio
async def test_job_match_encrypt_roundtrip(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    email = await _seed_email(test_session, user=user)

    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    repo = JobMatchesRepo(cipher=cipher)

    row = await repo.upsert(
        test_session,
        _payload(
            email_id=email.id,
            user_id=user.id,
            match_reason="Strong fit — compensation + remote policy align.",
        ),
    )
    assert row.match_reason_ct != b"Strong fit"
    assert row.passed_filter is True
    assert row.filter_version == 3

    plaintext = repo.decrypt_reason(row=row, user_id=user.id)
    assert plaintext == "Strong fit — compensation + remote policy align."


@pytest.mark.asyncio
async def test_job_match_passthrough_mode_when_cipher_is_none(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    email = await _seed_email(test_session, user=user)

    repo = JobMatchesRepo(cipher=None)
    row = await repo.upsert(
        test_session,
        _payload(email_id=email.id, user_id=user.id, match_reason="plain"),
    )
    # Pass-through stores the UTF-8 bytes as-is.
    assert row.match_reason_ct == b"plain"
    assert repo.decrypt_reason(row=row, user_id=user.id) == "plain"


@pytest.mark.asyncio
async def test_job_match_upsert_replaces_row_in_place(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    email = await _seed_email(test_session, user=user)

    repo = JobMatchesRepo(cipher=None)
    await repo.upsert(
        test_session,
        _payload(email_id=email.id, user_id=user.id, match_reason="first"),
    )
    await repo.upsert(
        test_session,
        _payload(email_id=email.id, user_id=user.id, match_reason="second"),
    )

    rows = (await test_session.execute(select(JobMatch))).scalars().all()
    assert len(rows) == 1
    assert repo.decrypt_reason(row=rows[0], user_id=user.id) == "second"


@pytest.mark.asyncio
async def test_job_match_empty_reason_roundtrips(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    email = await _seed_email(test_session, user=user)

    repo = JobMatchesRepo(cipher=None)
    # Upsert with empty reason — the repo replaces empty bytes with a
    # sentinel, and decrypt turns it back into an empty string.
    row = await repo.upsert(
        test_session,
        _payload(email_id=email.id, user_id=user.id, match_reason=""),
    )
    assert repo.decrypt_reason(row=row, user_id=user.id) == ""
