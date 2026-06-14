"""Integration tests for the ``/api/v1/emails`` router."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import db_session
from app.api.session import SESSION_COOKIE_NAME, sign_cookie
from app.core.config import Settings, get_settings
from app.core.consent import CURRENT_PRIVACY_POLICY_VERSION, CURRENT_TERMS_VERSION
from app.db.models import ConnectedAccount, Email, OAuthToken, User
from app.domain.providers import MarkReadResult, MessageId, ProviderCredentials
from app.main import app
from app.services.classification.repository import ClassificationsRepo, ClassificationWrite
from app.services.gmail.oauth import GMAIL_MODIFY_SCOPE, GMAIL_READONLY_SCOPE
from app.services.summarization.repository import SummariesRepo, SummaryEmailWrite


class _PlainTokenCipher:
    """Test cipher that treats DB token bytes as plaintext."""

    def decrypt(self, ciphertext: object, context: dict[str, str]) -> bytes:
        """Return plaintext bytes from an ``EncryptedBlob``-like object.

        Args:
            ciphertext: Object carrying a ``ciphertext`` attribute.
            context: Encryption context, ignored by the test double.

        Returns:
            The stored bytes.
        """
        del context

        return bytes(ciphertext.ciphertext)


class _FakeProvider:
    """Mailbox provider test double for mark-read endpoint tests."""

    kind: Literal["gmail", "outlook", "imap"] = "gmail"

    def __init__(self) -> None:
        self.calls: list[list[MessageId]] = []

    async def mark_read(
        self,
        credentials: ProviderCredentials,
        message_ids: list[MessageId],
    ) -> MarkReadResult:
        """Record message ids and return a successful provider result.

        Args:
            credentials: Decrypted provider credentials.
            message_ids: Provider ids selected by the endpoint.

        Returns:
            Successful mark-read result for every id.
        """
        del credentials

        self.calls.append(message_ids)
        return MarkReadResult(marked=tuple(message_ids))


@pytest_asyncio.fixture()
async def api_session(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def _settings() -> Settings:
        return Settings(
            env="test",
            runtime="local",
            log_level="info",
            session_signing_key="test-key",
        )

    app.dependency_overrides[db_session] = _override
    app.dependency_overrides[get_settings] = _settings
    try:
        yield factory
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_emails_filters_offset_and_review_flag(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user = await _seed_user(api_session)
    await _seed_email_rows(api_session, user=user)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        must_read = client.get(
            "/api/v1/emails?bucket=must_read",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert must_read.status_code == 200, must_read.text
        assert must_read.json()["total"] == 1
        assert must_read.json()["emails"][0]["needs_review"] is True

        query = client.get(
            "/api/v1/emails?q=quarterly",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert query.status_code == 200, query.text
        assert query.json()["total"] == 1
        assert query.json()["emails"][0]["subject"] == "Quarterly planning"

        sender = client.get(
            "/api/v1/emails?sender=news@example.com",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert sender.status_code == 200, sender.text
        assert sender.json()["total"] == 1
        assert sender.json()["emails"][0]["bucket"] == "good_to_read"

        with_summary = client.get(
            "/api/v1/emails?has_summary=true",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert with_summary.status_code == 200, with_summary.text
        assert with_summary.json()["total"] == 2

        future = client.get(
            "/api/v1/emails?received_after=2099-01-01T00:00:00Z",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert future.status_code == 200, future.text
        assert future.json()["total"] == 0

        second_page = client.get(
            "/api/v1/emails?limit=1&offset=1",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert second_page.status_code == 200, second_page.text
        assert second_page.json()["total"] == 3
        assert second_page.json()["emails"][0]["subject"] == "Weekly digest"

        legacy_bucket = client.get(
            "/api/v1/emails?bucket=waste",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert legacy_bucket.status_code == 422


@pytest.mark.asyncio
async def test_mark_read_by_ids_updates_gmail_and_hides_email(
    api_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _seed_user(api_session)
    await _seed_email_rows(api_session, user=user)
    email = await _email_by_subject(api_session, "Quarterly planning")
    await _seed_oauth_token(api_session, account_id=email.account_id, scopes=(GMAIL_MODIFY_SCOPE,))
    provider = _FakeProvider()
    _patch_mark_read_deps(monkeypatch=monkeypatch, provider=provider)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/emails/mark-read",
            json={"email_ids": [str(email.id)]},
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"marked": 1, "failed": []}

        hidden = client.get(
            "/api/v1/emails?bucket=must_read",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert hidden.status_code == 200, hidden.text
        assert hidden.json()["total"] == 0

    assert provider.calls == [[email.gmail_message_id]]
    updated = await _email_by_subject(api_session, "Quarterly planning")
    assert "UNREAD" not in updated.labels


@pytest.mark.asyncio
async def test_mark_read_by_category_selects_unread_owned_rows(
    api_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _seed_user(api_session)
    await _seed_email_rows(api_session, user=user)
    email = await _email_by_subject(api_session, "Receipt")
    await _seed_oauth_token(api_session, account_id=email.account_id, scopes=(GMAIL_MODIFY_SCOPE,))
    provider = _FakeProvider()
    _patch_mark_read_deps(monkeypatch=monkeypatch, provider=provider)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/emails/mark-read",
            json={"category": "ignore"},
            cookies={SESSION_COOKIE_NAME: cookie},
        )

    assert response.status_code == 200, response.text
    assert response.json()["marked"] == 1
    assert provider.calls == [[email.gmail_message_id]]


@pytest.mark.asyncio
async def test_mark_read_rejects_unowned_email_id(
    api_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _seed_user(api_session)
    other = await _seed_user(api_session, email="other@example.com")
    await _seed_email_rows(api_session, user=other)
    email = await _email_by_subject(api_session, "Quarterly planning")
    provider = _FakeProvider()
    _patch_mark_read_deps(monkeypatch=monkeypatch, provider=provider)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/emails/mark-read",
            json={"email_ids": [str(email.id)]},
            cookies={SESSION_COOKIE_NAME: cookie},
            headers={"x-request-id": "test-request-404"},
        )

    assert response.status_code == 404, response.text
    assert response.json() == {
        "code": "email_not_found",
        "message": "Email not found.",
        "details": {"selector": "email_ids"},
        "requestId": "test-request-404",
    }
    assert provider.calls == []


@pytest.mark.asyncio
async def test_mark_read_requires_gmail_modify_reconsent(
    api_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _seed_user(api_session)
    await _seed_email_rows(api_session, user=user)
    email = await _email_by_subject(api_session, "Quarterly planning")
    await _seed_oauth_token(
        api_session, account_id=email.account_id, scopes=(GMAIL_READONLY_SCOPE,)
    )
    provider = _FakeProvider()
    _patch_mark_read_deps(monkeypatch=monkeypatch, provider=provider)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/emails/mark-read",
            json={"email_ids": [str(email.id)]},
            cookies={SESSION_COOKIE_NAME: cookie},
            headers={"x-request-id": "test-request-409"},
        )

    assert response.status_code == 409, response.text
    assert response.json() == {
        "code": "gmail_reauthorization_required",
        "message": "Gmail re-authorization is required before mark-read.",
        "details": {"accountId": str(email.account_id), "scope": "gmail.modify"},
        "requestId": "test-request-409",
    }
    assert provider.calls == []


@pytest.mark.asyncio
async def test_mark_read_requires_legal_consent(
    api_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _seed_user(api_session, accepted=False)
    await _seed_email_rows(api_session, user=user)
    email = await _email_by_subject(api_session, "Quarterly planning")
    provider = _FakeProvider()
    _patch_mark_read_deps(monkeypatch=monkeypatch, provider=provider)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/emails/mark-read",
            json={"email_ids": [str(email.id)]},
            cookies={SESSION_COOKIE_NAME: cookie},
        )

    assert response.status_code == 451, response.text
    assert response.json() == {"detail": "legal_consent_required"}
    assert provider.calls == []


async def _seed_user(
    factory: async_sessionmaker[AsyncSession],
    *,
    email: str = "me@example.com",
    accepted: bool = True,
) -> User:
    """Insert a user and one active Gmail account.

    Args:
        factory: Async session factory.
        email: User and connected account email.
        accepted: Whether to seed current legal consent.

    Returns:
        Persisted user row.
    """
    async with factory() as session:
        user = User(email=email, tz="UTC", status="active")
        if accepted:
            user.privacy_policy_version_accepted = CURRENT_PRIVACY_POLICY_VERSION
            user.terms_version_accepted = CURRENT_TERMS_VERSION
        session.add(user)
        await session.flush()
        session.add(
            ConnectedAccount(
                user_id=user.id,
                provider="gmail",
                email=email,
                status="active",
            ),
        )
        await session.commit()
        await session.refresh(user)
        return user


async def _email_by_subject(
    factory: async_sessionmaker[AsyncSession],
    subject: str,
) -> Email:
    """Load one email by subject for endpoint tests.

    Args:
        factory: Async session factory.
        subject: Subject to match.

    Returns:
        Matching email row.
    """
    async with factory() as session:
        email = (await session.execute(select(Email).where(Email.subject == subject))).scalar_one()
        await session.refresh(email)
        return email


async def _seed_oauth_token(
    factory: async_sessionmaker[AsyncSession],
    *,
    account_id: UUID,
    scopes: tuple[str, ...],
) -> None:
    """Insert plaintext OAuth token bytes for mark-read endpoint tests.

    Args:
        factory: Async session factory.
        account_id: Connected account id.
        scopes: Granted OAuth scopes.
    """
    async with factory() as session:
        session.add(
            OAuthToken(
                account_id=account_id,
                access_token_ct=b"access",
                refresh_token_ct=b"refresh",
                scope=list(scopes),
                expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            ),
        )
        await session.commit()


def _patch_mark_read_deps(
    *,
    monkeypatch: pytest.MonkeyPatch,
    provider: _FakeProvider,
) -> None:
    """Patch Gmail provider and KMS cipher construction for endpoint tests.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        provider: Fake provider returned by the router factory.
    """
    from app.api.v1 import emails as emails_api

    monkeypatch.setattr(emails_api, "_token_cipher_for", lambda settings: _PlainTokenCipher())
    monkeypatch.setattr(emails_api, "_gmail_provider_for", lambda http_client: provider)


async def _seed_email_rows(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
) -> None:
    now = datetime.now(tz=UTC)
    async with factory() as session:
        account = (
            await session.execute(
                select(ConnectedAccount).where(ConnectedAccount.user_id == user.id)
            )
        ).scalar_one_or_none()
        assert account is not None
        account_id = account.id
        rows = (
            ("m-1", "Quarterly planning", "leadership@example.com", "must_read", True, 0),
            ("m-2", "Weekly digest", "news@example.com", "good_to_read", False, 1),
            ("m-3", "Receipt", "billing@example.com", "ignore", False, 2),
        )
        for gmail_id, subject, sender, label, needs_review, minutes_ago in rows:
            email = Email(
                account_id=account_id,
                gmail_message_id=gmail_id,
                thread_id=f"t-{gmail_id}",
                internal_date=now - timedelta(minutes=minutes_ago),
                from_addr=sender,
                to_addrs=[],
                cc_addrs=[],
                subject=subject,
                snippet=subject,
                labels=["UNREAD"],
                content_hash=hashlib.sha256(gmail_id.encode()).digest(),
            )
            session.add(email)
            await session.flush()
            await ClassificationsRepo(cipher=None).upsert(
                session,
                ClassificationWrite(
                    email_id=email.id,
                    label=label,
                    score=Decimal("0.900"),
                    rubric_version=1,
                    prompt_version_id=None,
                    decision_source="model",
                    model="gemini",
                    tokens_in=1,
                    tokens_out=1,
                    is_newsletter=False,
                    reasons={"reasons": [subject]},
                    user_id=user.id,
                    needs_review=needs_review,
                ),
            )
            if label != "good_to_read":
                await SummariesRepo(cipher=None).upsert_email(
                    session,
                    SummaryEmailWrite(
                        email_id=email.id,
                        user_id=user.id,
                        prompt_version_id=None,
                        model="gemini",
                        tokens_in=1,
                        tokens_out=1,
                        body_md=f"{subject} summary",
                        entities=(),
                        confidence=Decimal("0.900"),
                        cache_hit=False,
                        batch_id=None,
                    ),
                )
        await session.commit()
