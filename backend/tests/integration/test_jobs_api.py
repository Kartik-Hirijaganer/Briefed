"""API tests for the ``/api/v1/jobs`` read router (plan §14 Phase 4).

Covers:

* default response is the curated list — only ``passed_filter=True``
  rows whose ``match_score >= 0.7``.
* ``include_filtered=true`` surfaces every owned row.
* cross-user isolation: caller never sees another owner's matches.
* ``match_reason`` is decrypted before the response goes out.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import db_session
from app.api.session import SESSION_COOKIE_NAME, sign_cookie
from app.core.config import Settings, get_settings
from app.db.models import (
    ConnectedAccount,
    Email,
    User,
)
from app.main import app
from app.services.jobs.repository import JobMatchesRepo, JobMatchWrite


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


async def _seed_user_with_email(
    factory: async_sessionmaker[AsyncSession],
    *,
    email_addr: str,
    gmail_id: str,
) -> tuple[User, Email]:
    async with factory() as session:
        user = User(email=email_addr, tz="UTC", status="active")
        session.add(user)
        await session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email=email_addr,
            status="active",
        )
        session.add(account)
        await session.flush()
        email = Email(
            account_id=account.id,
            gmail_message_id=gmail_id,
            thread_id=f"t-{gmail_id}",
            internal_date=datetime.now(tz=UTC),
            from_addr="recruiter@acme.example",
            to_addrs=[],
            cc_addrs=[],
            subject="Staff Backend Engineer",
            snippet="Snippet.",
            labels=[],
            content_hash=hashlib.sha256(gmail_id.encode()).digest(),
        )
        session.add(email)
        await session.commit()
        await session.refresh(user)
        await session.refresh(email)
        return user, email


async def _seed_extra_email(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    gmail_id: str,
) -> Email:
    async with factory() as session:
        # Reuse the user's existing connected account.
        from sqlalchemy import select

        account = (
            await session.execute(
                select(ConnectedAccount).where(ConnectedAccount.user_id == user.id),
            )
        ).scalar_one()
        email = Email(
            account_id=account.id,
            gmail_message_id=gmail_id,
            thread_id=f"t-{gmail_id}",
            internal_date=datetime.now(tz=UTC),
            from_addr="recruiter@acme.example",
            to_addrs=[],
            cc_addrs=[],
            subject="Senior Backend Engineer",
            snippet="Snippet.",
            labels=[],
            content_hash=hashlib.sha256(gmail_id.encode()).digest(),
        )
        session.add(email)
        await session.commit()
        await session.refresh(email)
        return email


async def _write_job_match(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    email: Email,
    match_score: Decimal,
    passed_filter: bool,
    match_reason: str = "Strong fit.",
) -> None:
    repo = JobMatchesRepo(cipher=None)
    async with factory() as session:
        await repo.upsert(
            session,
            JobMatchWrite(
                email_id=email.id,
                user_id=user.id,
                title="Staff Backend Engineer",
                company="Acme",
                location="US",
                remote=True,
                comp_min=210000,
                comp_max=260000,
                currency="USD",
                comp_phrase="$210k-$260k",
                seniority="staff",
                source_url="https://acme.example/jobs",
                match_score=match_score,
                filter_version=1,
                passed_filter=passed_filter,
                prompt_version_id=None,
                model="gemini-1.5-flash",
                tokens_in=120,
                tokens_out=60,
                match_reason=match_reason,
            ),
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_curated_jobs_filters_failed_rows(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user, email_pass = await _seed_user_with_email(
        api_session,
        email_addr="me@x.com",
        gmail_id="m-pass",
    )
    email_fail = await _seed_extra_email(
        api_session,
        user=user,
        gmail_id="m-fail",
    )

    await _write_job_match(
        api_session,
        user=user,
        email=email_pass,
        match_score=Decimal("0.92"),
        passed_filter=True,
    )
    await _write_job_match(
        api_session,
        user=user,
        email=email_fail,
        match_score=Decimal("0.50"),
        passed_filter=False,
        match_reason="Below confidence floor.",
    )

    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        curated = client.get(
            "/api/v1/jobs",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert curated.status_code == 200, curated.text
        matches = curated.json()["matches"]
        assert len(matches) == 1
        assert matches[0]["passed_filter"] is True
        assert matches[0]["match_reason"] == "Strong fit."

        full = client.get(
            "/api/v1/jobs",
            params={"include_filtered": True},
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert full.status_code == 200
        assert len(full.json()["matches"]) == 2


@pytest.mark.asyncio
async def test_jobs_endpoint_isolates_owners(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user_a, email_a = await _seed_user_with_email(
        api_session,
        email_addr="a@x.com",
        gmail_id="m-a",
    )
    user_b, email_b = await _seed_user_with_email(
        api_session,
        email_addr="b@x.com",
        gmail_id="m-b",
    )
    await _write_job_match(
        api_session,
        user=user_a,
        email=email_a,
        match_score=Decimal("0.90"),
        passed_filter=True,
        match_reason="A fit.",
    )
    await _write_job_match(
        api_session,
        user=user_b,
        email=email_b,
        match_score=Decimal("0.91"),
        passed_filter=True,
        match_reason="B fit.",
    )

    cookie_a = sign_cookie({"user_id": str(user_a.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/jobs",
            cookies={SESSION_COOKIE_NAME: cookie_a},
        )
        assert response.status_code == 200
        matches = response.json()["matches"]
        assert len(matches) == 1
        assert matches[0]["match_reason"] == "A fit."


@pytest.mark.asyncio
async def test_curated_excludes_low_confidence_pass(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user, email = await _seed_user_with_email(
        api_session,
        email_addr="me@x.com",
        gmail_id="m-low",
    )
    # passed_filter=True but match_score below the digest floor →
    # excluded from the curated list (mirrors the worker's gate).
    await _write_job_match(
        api_session,
        user=user,
        email=email,
        match_score=Decimal("0.40"),
        passed_filter=True,
    )

    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        curated = client.get(
            "/api/v1/jobs",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert curated.status_code == 200
        assert curated.json()["matches"] == []

        full = client.get(
            "/api/v1/jobs",
            params={"include_filtered": True},
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert len(full.json()["matches"]) == 1


@pytest.mark.asyncio
async def test_jobs_endpoint_requires_session(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/jobs")
        assert response.status_code == 401
