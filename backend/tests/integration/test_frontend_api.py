"""Integration tests for the Phase 6 PWA aggregate API surface."""

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
    DigestRun,
    Email,
    TechNewsCluster,
    TechNewsClusterMember,
    User,
)
from app.main import app
from app.services.classification.repository import ClassificationsRepo, ClassificationWrite
from app.services.summarization.repository import SummariesRepo, SummaryTechNewsWrite


@pytest_asyncio.fixture()
async def api_session(
    test_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Override FastAPI DB/settings dependencies for API tests."""
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
async def test_preferences_patch_and_manual_run_history(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """Preferences persist and manual runs are pollable/listable."""
    user = await _seed_user_with_account(api_session, email="me@x.example")
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        get_response = client.get(
            "/api/v1/preferences",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert get_response.status_code == 200, get_response.text
        assert get_response.json()["auto_execution_enabled"] is True

        patch_response = client.patch(
            "/api/v1/preferences",
            json={
                "auto_execution_enabled": False,
                "digest_send_hour_utc": 9,
                "retention_policy_json": {"summaries_days": 30},
            },
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert patch_response.status_code == 200, patch_response.text
        assert patch_response.json()["digest_send_hour_utc"] == 9
        assert patch_response.json()["retention_policy_json"] == {"summaries_days": 30}

        run_response = client.post(
            "/api/v1/runs",
            json={"kind": "manual"},
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert run_response.status_code == 202, run_response.text
        run_payload = run_response.json()
        assert run_payload["accounts_queued"] == 1

        status_response = client.get(
            f"/api/v1/runs/{run_payload['run_id']}",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["status"] == "queued"

        history_response = client.get(
            "/api/v1/history",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert history_response.status_code == 200, history_response.text
        assert history_response.json()["runs"][0]["id"] == run_payload["run_id"]


@pytest.mark.asyncio
async def test_manual_run_rate_limit_returns_429(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """``POST /api/v1/runs`` enforces ``manual_run_daily_cap`` (plan §19.16)."""
    from app.core import rate_limit as rate_limit_module
    from app.core.rate_limit import ManualRunRateLimiter, reset_manual_run_limiter

    reset_manual_run_limiter()
    # Drop the cap to 1 so the second request trips the limiter immediately.
    rate_limit_module._LIMITER = ManualRunRateLimiter(capacity=1)
    user = await _seed_user_with_account(api_session, email="rate@x.example")
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/v1/runs",
                json={"kind": "manual"},
                cookies={SESSION_COOKIE_NAME: cookie},
            )
            assert first.status_code == 202, first.text

            second = client.post(
                "/api/v1/runs",
                json={"kind": "manual"},
                cookies={SESSION_COOKIE_NAME: cookie},
            )
            assert second.status_code == 429, second.text
            assert "Retry-After" in second.headers
    finally:
        reset_manual_run_limiter()


@pytest.mark.asyncio
async def test_security_headers_present(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """Every response carries the OWASP-baseline header set (plan §14 Phase 8)."""
    user = await _seed_user_with_account(api_session, email="sec@x.example")
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/preferences",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert resp.status_code == 200, resp.text
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert "max-age=31536000" in resp.headers.get("Strict-Transport-Security", "")
        assert "geolocation=()" in resp.headers.get("Permissions-Policy", "")


@pytest.mark.asyncio
async def test_digest_today_and_news_return_owned_data(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    """Digest and news aggregate endpoints return decrypted owned rows."""
    user = await _seed_user_with_account(api_session, email="me@x.example")
    email = await _seed_classified_email(api_session, user=user)
    await _seed_successful_run(api_session, user=user)
    await _seed_news_cluster(api_session, user=user, email=email)
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")

    with TestClient(app) as client:
        digest_response = client.get(
            "/api/v1/digest/today",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert digest_response.status_code == 200, digest_response.text
        digest = digest_response.json()
        assert digest["counts"]["must_read"] == 1
        assert digest["must_read_preview"][0]["subject"] == "Quarterly planning"
        assert digest["last_successful_run_at"] is not None

        news_response = client.get(
            "/api/v1/news",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert news_response.status_code == 200, news_response.text
        news = news_response.json()
        assert news["clusters"][0]["label"] == "AI infrastructure"
        assert "GPU capacity" in news["clusters"][0]["summary_md"]


async def _seed_user_with_account(
    factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
) -> User:
    """Insert one user with one active connected account."""
    async with factory() as session:
        user = User(email=email, tz="UTC", status="active")
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


async def _seed_classified_email(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
) -> Email:
    """Insert one must-read email and classification row."""
    async with factory() as session:
        account = await _account_for(session, user=user)
        email = Email(
            account_id=account.id,
            gmail_message_id="m-planning",
            thread_id="t-planning",
            internal_date=datetime.now(tz=UTC),
            from_addr="leadership@company.example",
            to_addrs=[],
            cc_addrs=[],
            subject="Quarterly planning",
            snippet="Planning packet attached.",
            labels=[],
            content_hash=hashlib.sha256(b"m-planning").digest(),
        )
        session.add(email)
        await session.flush()
        await ClassificationsRepo(cipher=None).upsert(
            session,
            ClassificationWrite(
                email_id=email.id,
                label="must_read",
                score=Decimal("0.950"),
                rubric_version=1,
                prompt_version_id=None,
                decision_source="rule",
                model="",
                tokens_in=0,
                tokens_out=0,
                is_newsletter=False,
                is_job_candidate=False,
                reasons={"reasons": ["Executive planning context."]},
                user_id=user.id,
            ),
        )
        await session.commit()
        await session.refresh(email)
        return email


async def _seed_successful_run(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
) -> None:
    """Insert one completed digest run."""
    now = datetime.now(tz=UTC)
    async with factory() as session:
        session.add(
            DigestRun(
                user_id=user.id,
                status="complete",
                trigger_type="scheduled",
                started_at=now,
                completed_at=now,
                stats={"ingested": 1, "classified": 1, "summarized": 1, "new_must_read": 1},
                cost_cents=1,
            ),
        )
        await session.commit()


async def _seed_news_cluster(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    email: Email,
) -> None:
    """Insert one tech-news cluster with encrypted summary in pass-through mode."""
    async with factory() as session:
        cluster = TechNewsCluster(
            user_id=user.id,
            run_id=None,
            cluster_key="ai_infra",
            topic_hint="AI infrastructure",
            member_count=1,
        )
        session.add(cluster)
        await session.flush()
        session.add(
            TechNewsClusterMember(cluster_id=cluster.id, email_id=email.id, sort_order=0),
        )
        await SummariesRepo(cipher=None).upsert_tech_news_cluster(
            session,
            SummaryTechNewsWrite(
                cluster_id=cluster.id,
                user_id=user.id,
                prompt_version_id=None,
                model="",
                tokens_in=0,
                tokens_out=0,
                body_md="GPU capacity is tightening across cloud providers.",
                sources=("Quarterly planning",),
                confidence=Decimal("0.900"),
                cache_hit=False,
                batch_id=None,
            ),
        )
        await session.commit()


async def _account_for(session: AsyncSession, *, user: User) -> ConnectedAccount:
    """Return the user's only connected account."""
    from sqlalchemy import select

    return (
        await session.execute(
            select(ConnectedAccount).where(ConnectedAccount.user_id == user.id),
        )
    ).scalar_one()
