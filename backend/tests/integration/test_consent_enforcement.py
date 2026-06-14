"""Integration tests for legal-consent enforcement paths."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import app.api.v1.unsubscribes as unsubscribes_module
from app.api.deps import db_session
from app.api.session import SESSION_COOKIE_NAME, sign_cookie
from app.core import rate_limit as rate_limit_module
from app.core.app_config import AppConfig, FeatureConfig
from app.core.config import Settings, get_settings
from app.core.consent import (
    CURRENT_PRIVACY_POLICY_VERSION,
    CURRENT_TERMS_VERSION,
    enforce_legal_consent,
    has_current_legal_consent,
)
from app.core.rate_limit import ManualRunRateLimiter, reset_manual_run_limiter
from app.db.models import ConnectedAccount, DigestRun, Email, User
from app.main import app
from app.workers.handlers.fanout import FanoutDeps, run_fanout


class _FakeSqs:
    """In-memory SQS sender for fanout consent tests.

    Attributes:
        sent: Captured ``send_message`` inputs.
    """

    sent: list[dict[str, Any]]

    def __init__(self) -> None:
        """Initialize an empty sent-message list."""
        self.sent = []

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        """Record one outbound message.

        Args:
            QueueUrl: Queue URL the handler selected.
            MessageBody: Serialized SQS payload.

        Returns:
            Minimal boto3-compatible response.
        """
        self.sent.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": str(len(self.sent))}


@pytest_asyncio.fixture()
async def api_session(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Override app DB/settings dependencies for consent enforcement tests.

    Args:
        test_engine: In-memory SQLite engine from the shared fixture.

    Yields:
        Async sessionmaker used by API requests and seed helpers.
    """
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override() -> AsyncIterator[AsyncSession]:
        """Yield a committed API session bound to the test engine.

        Yields:
            Async database session for one request.
        """
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def _settings() -> Settings:
        """Return deterministic settings for signed test cookies.

        Returns:
            Test settings with a fixed session signing key.
        """
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


@pytest.mark.parametrize(
    ("privacy_version", "terms_version", "expected"),
    [
        (0, 0, False),
        (CURRENT_PRIVACY_POLICY_VERSION, 0, False),
        (0, CURRENT_TERMS_VERSION, False),
        (CURRENT_PRIVACY_POLICY_VERSION, CURRENT_TERMS_VERSION, True),
        (CURRENT_PRIVACY_POLICY_VERSION + 1, CURRENT_TERMS_VERSION + 1, True),
    ],
)
def test_legal_consent_helper_truth_table(
    privacy_version: int,
    terms_version: int,
    expected: bool,
) -> None:
    """Consent helper requires both accepted versions to be current."""
    user = User(
        email="truth@example.com",
        tz="UTC",
        status="active",
        privacy_policy_version_accepted=privacy_version,
        terms_version_accepted=terms_version,
    )

    assert has_current_legal_consent(user) is expected
    if expected:
        enforce_legal_consent(user)
    else:
        with pytest.raises(HTTPException) as exc_info:
            enforce_legal_consent(user)
        assert exc_info.value.status_code == 451
        assert exc_info.value.detail == "legal_consent_required"


async def test_manual_scan_requires_consent_before_rate_limit(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """Manual scan returns 451 before consuming or reporting quota."""
    user = await _seed_user(api_session, email="manual@example.com", accepted=False)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    reset_manual_run_limiter()
    rate_limit_module._LIMITER = ManualRunRateLimiter(capacity=1)
    rate_limit_module._LIMITER.check(user.id)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/runs",
                json={"kind": "manual"},
                cookies={SESSION_COOKIE_NAME: cookie},
            )
    finally:
        reset_manual_run_limiter()

    assert response.status_code == 451, response.text
    assert response.json() == {"detail": "legal_consent_required"}


async def test_fanout_skips_users_without_current_consent(
    test_session: AsyncSession,
) -> None:
    """Scheduled fanout does not enqueue Gmail work for unconsented users."""
    user = User(
        email="fanout@example.com",
        tz="UTC",
        status="active",
        schedule_frequency="once_daily",
        schedule_times_local=["08:00"],
        schedule_timezone="UTC",
    )
    test_session.add(user)
    await test_session.flush()
    test_session.add(
        ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email=user.email,
            status="active",
        ),
    )
    await test_session.commit()

    sqs = _FakeSqs()
    deps = FanoutDeps(
        session=test_session,
        sqs=sqs,
        ingest_queue_url="https://sqs.local/ingest",
    )
    with patch(
        "app.workers.handlers.fanout.utcnow",
        return_value=datetime(2026, 4, 25, 8, 5, tzinfo=ZoneInfo("UTC")),
    ):
        enqueued = await run_fanout(deps=deps)

    assert enqueued == 0
    assert sqs.sent == []
    runs = (await test_session.execute(select(DigestRun))).scalars().all()
    assert runs == []


async def test_mark_read_requires_current_consent(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """Mark-read rejects stale legal consent before Gmail mutation work."""
    user = await _seed_user(api_session, email="mark-read@example.com", accepted=False)
    email_id = await _seed_email(api_session, user=user)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/emails/mark-read",
            json={"email_ids": [str(email_id)]},
            cookies={SESSION_COOKIE_NAME: cookie},
        )

    assert response.status_code == 451, response.text
    assert response.json() == {"detail": "legal_consent_required"}


async def test_unsubscribe_execute_requires_current_consent(
    api_session: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute-unsubscribe rejects stale consent before row lookup or executor work."""
    monkeypatch.setattr(
        unsubscribes_module,
        "_APP_CONFIG",
        AppConfig(features=FeatureConfig(unsubscribe_execute=True)),
    )
    user = await _seed_user(api_session, email="unsubscribe@example.com", accepted=False)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/unsubscribes/{uuid4()}/execute",
            json={"confirm": True},
            cookies={SESSION_COOKIE_NAME: cookie},
        )

    assert response.status_code == 451, response.text
    assert response.json() == {"detail": "legal_consent_required"}


async def _seed_user(
    factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
    accepted: bool,
) -> User:
    """Insert one user with one active account.

    Args:
        factory: Async sessionmaker bound to the test engine.
        email: User and account email.
        accepted: Whether to seed current accepted legal versions.

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


async def _seed_email(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
) -> UUID:
    """Insert one unread Gmail email row for mark-read consent tests.

    Args:
        factory: Async sessionmaker bound to the test engine.
        user: User whose account owns the email.

    Returns:
        New email id.
    """
    async with factory() as session:
        account = (
            await session.execute(
                select(ConnectedAccount).where(ConnectedAccount.user_id == user.id),
            )
        ).scalar_one()
        email = Email(
            account_id=account.id,
            gmail_message_id="m-consent",
            thread_id="t-consent",
            internal_date=datetime.now(tz=UTC),
            from_addr="sender@example.com",
            to_addrs=[],
            cc_addrs=[],
            subject="Consent check",
            snippet="Consent check",
            labels=["UNREAD"],
            content_hash=b"0" * 32,
        )
        session.add(email)
        await session.commit()
        return email.id
