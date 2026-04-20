"""Tests for the ingest SQS-handler composition (unwrap → run → persist)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import EncryptionContext, EnvelopeCipher, token_context
from app.db.models import ConnectedAccount, Email, OAuthToken, User
from app.domain.providers import (
    MailboxProvider,
    MessageId,
    ProviderCredentials,
    RawMessage,
    SyncCursor,
)
from app.workers.handlers.ingest import IngestDeps, handle_ingest
from app.workers.messages import IngestMessage


class _FakeKms:
    def encrypt(
        self,
        *,
        KeyId: str,
        Plaintext: bytes,
        EncryptionContext: dict[str, str],
    ) -> dict[str, object]:
        return {"CiphertextBlob": b"F:" + Plaintext}

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,
        EncryptionContext: dict[str, str],
        KeyId: str | None = None,
    ) -> dict[str, object]:
        return {"Plaintext": CiphertextBlob[2:]}


@dataclass
class _DummyProvider(MailboxProvider):
    kind: Literal["gmail", "outlook", "imap"] = "gmail"
    messages: dict[MessageId, RawMessage] = field(default_factory=dict)

    async def list_new_ids(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> tuple[list[MessageId], SyncCursor]:
        return list(self.messages.keys()), cursor.model_copy(
            update={"history_id": 1, "stale": False},
        )

    async def get_messages(
        self,
        credentials: ProviderCredentials,
        ids: list[MessageId],
    ) -> list[RawMessage]:
        return [self.messages[i] for i in ids]

    async def refresh_cursor(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> SyncCursor:
        return cursor.model_copy(update={"stale": False})

    async def revoke(self, credentials: ProviderCredentials) -> None:
        return None


async def test_handle_ingest_decrypts_tokens_and_inserts_emails(
    test_session: AsyncSession,
) -> None:
    # Seed user + account + tokens (wrapped by fake KMS).
    user = User(email="u@x.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="u@x.com",
        status="active",
    )
    test_session.add(account)
    await test_session.flush()

    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    access_blob = cipher.encrypt(
        b"access-1",
        token_context(account_id=str(account.id), purpose="access_token"),
    )
    refresh_blob = cipher.encrypt(
        b"refresh-1",
        token_context(account_id=str(account.id), purpose="refresh_token"),
    )
    tokens = OAuthToken(
        account_id=account.id,
        access_token_ct=access_blob.ciphertext,
        refresh_token_ct=refresh_blob.ciphertext,
        scope=["gmail.readonly"],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    test_session.add(tokens)
    await test_session.commit()

    mime = b"Subject: Hi\r\nFrom: a@b.com\r\n\r\nbody"
    provider = _DummyProvider(
        messages={
            "m1": RawMessage(
                message_id="m1",
                thread_id="t1",
                internal_date_ms=1_700_000_000_000,
                raw_mime=mime,
                size_bytes=len(mime),
            )
        }
    )
    deps = IngestDeps(session=test_session, provider=provider, cipher=cipher)

    stats = await handle_ingest(
        IngestMessage(user_id=user.id, account_id=account.id),
        deps=deps,
    )
    await test_session.commit()
    assert stats.new == 1

    from sqlalchemy import select

    emails = (await test_session.execute(select(Email))).scalars().all()
    assert len(emails) == 1


async def test_handle_ingest_missing_tokens_raises(test_session: AsyncSession) -> None:
    import pytest

    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    provider = _DummyProvider()
    deps = IngestDeps(session=test_session, provider=provider, cipher=cipher)
    with pytest.raises(LookupError):
        await handle_ingest(
            IngestMessage(user_id=uuid4(), account_id=uuid4()),
            deps=deps,
        )


def test_encryption_context_object() -> None:
    # Keep quick visibility on the shared ctx helper.
    assert EncryptionContext(fields={"k": "v"}).as_kms_dict() == {"k": "v"}
