"""Tests for treating a rejected Gmail refresh token as terminal at ingest.

Ingest flags the account for reconnect and acks the SQS message instead
of burning redeliveries into the DLQ.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.consent import CURRENT_PRIVACY_POLICY_VERSION, CURRENT_TERMS_VERSION
from app.core.errors import AuthError, InvalidGrantError
from app.core.security import EnvelopeCipher, token_context
from app.db.models import Base, ConnectedAccount, DigestRun, OAuthToken, User
from app.domain.providers import (
    MarkReadResult,
    MessageId,
    ProviderCredentials,
    RawMessage,
    SyncCursor,
)
from app.workers.handlers.fanout import FanoutDeps, parse_ingest_body, run_fanout
from app.workers.handlers.ingest import IngestDeps, handle_ingest
from app.workers.messages import IngestMessage

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_INVALID_GRANT = {"error": "invalid_grant", "error_description": "Bad Request"}
_INVALID_CLIENT = {"error": "invalid_client", "error_description": "Unauthorized"}


class _FakeKms:
    """Reversible stand-in for KMS so token envelopes round-trip in-process."""

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


class _UnreachableProvider:
    """Mailbox provider that fails the test if ingest ever reaches Gmail."""

    kind: Literal["gmail", "outlook", "imap"] = "gmail"

    async def list_new_ids(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> tuple[list[MessageId], SyncCursor]:
        raise AssertionError("ingest must not list mail for this account")

    async def get_messages(
        self,
        credentials: ProviderCredentials,
        ids: list[MessageId],
    ) -> list[RawMessage]:
        raise AssertionError("ingest must not fetch mail for this account")

    async def mark_read(
        self,
        credentials: ProviderCredentials,
        message_ids: list[MessageId],
    ) -> MarkReadResult:
        raise AssertionError("ingest never marks mail read")

    async def refresh_cursor(
        self,
        credentials: ProviderCredentials,
        cursor: SyncCursor,
    ) -> SyncCursor:
        raise AssertionError("ingest must not refresh the cursor for this account")

    async def revoke(self, credentials: ProviderCredentials) -> None:
        raise AssertionError("ingest never revokes a grant")


def _token_endpoint(
    body: dict[str, str],
    *,
    status_code: int = 400,
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    """Return an HTTP client whose token endpoint always answers ``body``."""
    calls: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status_code=status_code, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler)), calls


async def _seed_account(
    session: AsyncSession,
    *,
    status: str = "active",
    expires_in: timedelta = timedelta(minutes=-1),
) -> tuple[User, ConnectedAccount, OAuthToken]:
    """Seed a consented user, one account, and tokens due for refresh."""
    user = User(
        email="owner@example.com",
        tz="UTC",
        status="active",
        privacy_policy_version_accepted=CURRENT_PRIVACY_POLICY_VERSION,
        terms_version_accepted=CURRENT_TERMS_VERSION,
    )
    session.add(user)
    await session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="mailbox@example.com",
        status=status,
    )
    session.add(account)
    await session.flush()
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    tokens = OAuthToken(
        account_id=account.id,
        access_token_ct=cipher.encrypt(
            b"access-1",
            token_context(account_id=str(account.id), purpose="access_token"),
        ).ciphertext,
        refresh_token_ct=cipher.encrypt(
            b"refresh-1",
            token_context(account_id=str(account.id), purpose="refresh_token"),
        ).ciphertext,
        scope=["https://www.googleapis.com/auth/gmail.readonly"],
        expires_at=datetime.now(UTC) + expires_in,
    )
    session.add(tokens)
    await session.commit()
    return user, account, tokens


def _deps(session: AsyncSession, http_client: httpx.AsyncClient) -> IngestDeps:
    """Build ingest deps wired to the fake KMS and a mocked token endpoint."""
    return IngestDeps(
        session=session,
        provider=_UnreachableProvider(),
        cipher=EnvelopeCipher(key_id="alias/test", client=_FakeKms()),
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        http_client=http_client,
    )


async def test_invalid_grant_flags_account_for_reconnect_and_skips_ingest(
    test_session: AsyncSession,
) -> None:
    user, account, tokens = await _seed_account(test_session)
    refresh_ct = bytes(tokens.refresh_token_ct)
    client, calls = _token_endpoint(_INVALID_GRANT)

    async with client:
        stats = await handle_ingest(
            IngestMessage(user_id=user.id, account_id=account.id),
            deps=_deps(test_session, client),
        )
    await test_session.commit()

    assert (stats.new, stats.duplicates, stats.email_ids) == (0, 0, ())
    assert [str(call.url) for call in calls] == [_TOKEN_URL]
    await test_session.refresh(account)
    assert account.status == "revoked"
    # Only the status flips: reconnect overwrites the tokens and restores
    # ``active``, and scheduled scans resume with no extra toggle.
    assert account.auto_scan_enabled is True
    stored = (
        await test_session.execute(select(OAuthToken).where(OAuthToken.account_id == account.id))
    ).scalar_one()
    assert bytes(stored.refresh_token_ct) == refresh_ct


async def test_other_oauth_rejection_still_raises_for_retry(
    test_session: AsyncSession,
) -> None:
    """``invalid_client`` is Briefed's misconfiguration, not the user's grant."""
    user, account, _tokens = await _seed_account(test_session)
    client, _calls = _token_endpoint(_INVALID_CLIENT, status_code=401)

    async with client:
        with pytest.raises(AuthError, match="invalid_client") as excinfo:
            await handle_ingest(
                IngestMessage(user_id=user.id, account_id=account.id),
                deps=_deps(test_session, client),
            )

    assert not isinstance(excinfo.value, InvalidGrantError)
    await test_session.rollback()
    await test_session.refresh(account)
    assert account.status == "active"


@pytest.mark.parametrize("status", ["revoked", "disabled"])
async def test_inactive_account_is_skipped_without_touching_google(
    test_session: AsyncSession,
    status: str,
) -> None:
    """In-flight messages for a flagged / disconnected account are acked."""
    user, account, _tokens = await _seed_account(test_session, status=status)
    client, calls = _token_endpoint(_INVALID_GRANT)

    async with client:
        stats = await handle_ingest(
            IngestMessage(user_id=user.id, account_id=account.id),
            deps=_deps(test_session, client),
        )

    assert stats.new == 0
    assert calls == []
    await test_session.refresh(account)
    assert account.status == status


async def test_removed_account_is_skipped(test_session: AsyncSession) -> None:
    user, _account, _tokens = await _seed_account(test_session)
    client, calls = _token_endpoint(_INVALID_GRANT)

    async with client:
        stats = await handle_ingest(
            IngestMessage(user_id=user.id, account_id=uuid4()),
            deps=_deps(test_session, client),
        )

    assert stats.new == 0
    assert calls == []


async def test_fanout_skips_account_flagged_for_reconnect(
    test_session: AsyncSession,
) -> None:
    user, flagged, _tokens = await _seed_account(test_session, status="revoked")
    user.schedule_frequency = "once_daily"
    user.schedule_times_local = ["08:00"]
    user.schedule_timezone = "UTC"
    healthy = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="healthy@example.com",
        status="active",
    )
    test_session.add(healthy)
    await test_session.commit()
    sent: list[str] = []

    class _Sqs:
        def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, str]:
            sent.append(MessageBody)
            return {"MessageId": str(len(sent))}

    with patch(
        "app.workers.handlers.fanout.utcnow",
        return_value=datetime(2026, 10, 27, 8, 5, tzinfo=UTC),
    ):
        enqueued = await run_fanout(
            deps=FanoutDeps(
                session=test_session,
                sqs=_Sqs(),
                ingest_queue_url="https://sqs.local/ingest",
            ),
        )

    assert enqueued == 1
    assert [parse_ingest_body(body).account_id for body in sent] == [healthy.id]
    assert flagged.id not in {parse_ingest_body(body).account_id for body in sent}


def test_sqs_dispatcher_acks_ingest_when_refresh_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End to end through the Lambda entrypoint: no ``batchItemFailures``.

    ``sqs_dispatcher`` runs its own event loop, hence file-backed SQLite
    with ``NullPool``.
    """
    from app import lambda_worker

    url = f"sqlite+aiosqlite:///{tmp_path / 'ingest.db'}"

    def factory() -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(
            create_async_engine(url, poolclass=NullPool),
            expire_on_commit=False,
            class_=AsyncSession,
        )

    async def _seed() -> tuple[UUID, UUID, UUID]:
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()
        async with factory()() as session:
            user, account, _tokens = await _seed_account(session)
            run = DigestRun(
                user_id=user.id,
                status="queued",
                trigger_type="scheduled",
                started_at=datetime.now(UTC),
                stats={"account_ids": [str(account.id)]},
                cost_cents=0,
            )
            session.add(run)
            await session.commit()
            return user.id, account.id, run.id

    async def _load(account_id: UUID, run_id: UUID) -> tuple[str, str]:
        async with factory()() as session:
            account = await session.get(ConnectedAccount, account_id)
            run = await session.get(DigestRun, run_id)
            assert account is not None
            assert run is not None
            return account.status, run.status

    async def _rejected_refresh(**_kwargs: object) -> object:
        raise InvalidGrantError("refresh token rejected: invalid_grant: Bad Request")

    user_id, account_id, run_id = asyncio.run(_seed())
    monkeypatch.setenv("BRIEFED_TOKEN_WRAP_KEY_ALIAS", "alias/test-token")
    monkeypatch.setenv("BRIEFED_CONTENT_KEY_ALIAS", "alias/test-content")
    monkeypatch.delenv("BRIEFED_CLASSIFY_QUEUE_URL", raising=False)
    monkeypatch.delenv("BRIEFED_SUMMARIZE_QUEUE_URL", raising=False)
    monkeypatch.setattr(lambda_worker, "_kms_client", _FakeKms)
    monkeypatch.setattr(
        lambda_worker,
        "_settings",
        lambda_worker._settings.model_copy(
            update={
                "google_oauth_client_id": "client-id",
                "google_oauth_client_secret": "client-secret",
            },
        ),
    )
    monkeypatch.setattr("app.db.session.get_sessionmaker", factory)
    monkeypatch.setattr("app.workers.handlers.ingest.refresh_access_token", _rejected_refresh)

    message = IngestMessage(user_id=user_id, account_id=account_id, run_id=run_id)
    result = lambda_worker.sqs_dispatcher(
        {
            "Records": [
                {
                    "messageId": "m-1",
                    "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:briefed-prod-ingest",
                    "body": message.model_dump_json(),
                },
            ],
        },
        None,
    )

    assert result == {"batchItemFailures": []}
    account_status, run_status = asyncio.run(_load(account_id, run_id))
    assert account_status == "revoked"
    # The run must not wait on an account that will never ingest.
    assert run_status == "complete"
