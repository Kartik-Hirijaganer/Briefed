"""API tests for the Phase 5 unsubscribe + hygiene routers.

Covers:

* ``GET /api/v1/unsubscribes`` — top-N list with dismissed rows hidden
  by default and cross-user isolation.
* ``POST /api/v1/unsubscribes/{id}/dismiss`` — persists dismissal + its
  timestamp and survives a reload (plan §14 Phase 5 exit criteria).
* ``POST /api/v1/unsubscribes/{id}/confirm`` — flips dismissal with no
  provider side-effect (ADR 0006 recommend-only).
* ``GET /api/v1/hygiene/stats`` — returns counters + top domains.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import db_session
from app.api.session import SESSION_COOKIE_NAME, sign_cookie
from app.core.config import Settings, get_settings
from app.db.models import ConnectedAccount, User
from app.main import app
from app.services.unsubscribe.repository import (
    UnsubscribeSuggestionsRepo,
    UnsubscribeSuggestionWrite,
)


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


async def _seed_user(
    factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
) -> tuple[User, ConnectedAccount]:
    async with factory() as session:
        user = User(email=email, tz="UTC", status="active")
        session.add(user)
        await session.flush()
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email=email,
            status="active",
        )
        session.add(account)
        await session.commit()
        await session.refresh(user)
        await session.refresh(account)
        return user, account


async def _write_suggestion(
    factory: async_sessionmaker[AsyncSession],
    *,
    user: User,
    account: ConnectedAccount,
    sender_email: str,
    sender_domain: str,
    confidence: Decimal,
    frequency: int,
    rationale: str = "Noisy promo sender.",
    list_unsub: bool = True,
    last_email_days_ago: int = 1,
) -> None:
    repo = UnsubscribeSuggestionsRepo(cipher=None)
    async with factory() as session:
        await repo.upsert(
            session,
            UnsubscribeSuggestionWrite(
                account_id=account.id,
                user_id=user.id,
                sender_domain=sender_domain,
                sender_email=sender_email,
                frequency_30d=frequency,
                engagement_score=Decimal("0.050"),
                waste_rate=Decimal("0.800"),
                list_unsubscribe=(
                    {
                        "http_urls": [f"https://{sender_domain}/unsub"],
                        "mailto": None,
                        "one_click": True,
                    }
                    if list_unsub
                    else None
                ),
                confidence=confidence,
                decision_source="rule",
                rationale=rationale,
                prompt_version_id=None,
                model="",
                tokens_in=0,
                tokens_out=0,
                last_email_at=datetime.now(tz=UTC) - timedelta(days=last_email_days_ago),
            ),
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_suggestions_sorts_by_confidence_and_hides_dismissed(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user, account = await _seed_user(api_session, email="me@x.example")
    await _write_suggestion(
        api_session,
        user=user,
        account=account,
        sender_email="deals@promo.example",
        sender_domain="promo.example",
        confidence=Decimal("0.92"),
        frequency=22,
    )
    await _write_suggestion(
        api_session,
        user=user,
        account=account,
        sender_email="news@b.example",
        sender_domain="b.example",
        confidence=Decimal("0.85"),
        frequency=10,
        rationale="Weekly digest.",
    )

    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/unsubscribes",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert response.status_code == 200, response.text
        suggestions = response.json()["suggestions"]
        assert [s["sender_email"] for s in suggestions] == [
            "deals@promo.example",
            "news@b.example",
        ]
        assert suggestions[0]["rationale"] == "Noisy promo sender."
        assert suggestions[0]["list_unsubscribe"]["one_click"] is True

        # Dismiss the top row; it should no longer surface by default.
        target_id = suggestions[0]["id"]
        dismiss = client.post(
            f"/api/v1/unsubscribes/{target_id}/dismiss",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert dismiss.status_code == 204

        after = client.get(
            "/api/v1/unsubscribes",
            cookies={SESSION_COOKIE_NAME: cookie},
        ).json()["suggestions"]
        assert [s["sender_email"] for s in after] == ["news@b.example"]

        with_dismissed = client.get(
            "/api/v1/unsubscribes",
            params={"include_dismissed": True},
            cookies={SESSION_COOKIE_NAME: cookie},
        ).json()["suggestions"]
        assert len(with_dismissed) == 2
        dismissed_row = next(s for s in with_dismissed if s["id"] == target_id)
        assert dismissed_row["dismissed"] is True
        assert dismissed_row["dismissed_at"] is not None


@pytest.mark.asyncio
async def test_confirm_dismisses_without_touching_provider(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user, account = await _seed_user(api_session, email="me@x.example")
    await _write_suggestion(
        api_session,
        user=user,
        account=account,
        sender_email="weekly@news.example",
        sender_domain="news.example",
        confidence=Decimal("0.90"),
        frequency=8,
    )
    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        target = client.get(
            "/api/v1/unsubscribes",
            cookies={SESSION_COOKIE_NAME: cookie},
        ).json()["suggestions"][0]
        response = client.post(
            f"/api/v1/unsubscribes/{target['id']}/confirm",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert response.status_code == 204
        after = client.get(
            "/api/v1/unsubscribes",
            params={"include_dismissed": True},
            cookies={SESSION_COOKIE_NAME: cookie},
        ).json()["suggestions"]
        assert after[0]["dismissed"] is True


@pytest.mark.asyncio
async def test_unsubscribes_endpoint_isolates_owners(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user_a, account_a = await _seed_user(api_session, email="a@x.example")
    user_b, account_b = await _seed_user(api_session, email="b@x.example")
    await _write_suggestion(
        api_session,
        user=user_a,
        account=account_a,
        sender_email="a-promo@a.example",
        sender_domain="a.example",
        confidence=Decimal("0.90"),
        frequency=10,
    )
    await _write_suggestion(
        api_session,
        user=user_b,
        account=account_b,
        sender_email="b-promo@b.example",
        sender_domain="b.example",
        confidence=Decimal("0.91"),
        frequency=12,
    )
    cookie_a = sign_cookie({"user_id": str(user_a.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/unsubscribes",
            cookies={SESSION_COOKIE_NAME: cookie_a},
        )
        assert response.status_code == 200
        suggestions = response.json()["suggestions"]
        assert len(suggestions) == 1
        assert suggestions[0]["sender_email"] == "a-promo@a.example"


@pytest.mark.asyncio
async def test_dismiss_requires_ownership(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user_a, _account_a = await _seed_user(api_session, email="a@x.example")
    user_b, account_b = await _seed_user(api_session, email="b@x.example")
    await _write_suggestion(
        api_session,
        user=user_b,
        account=account_b,
        sender_email="b-promo@b.example",
        sender_domain="b.example",
        confidence=Decimal("0.91"),
        frequency=12,
    )

    cookie_a = sign_cookie({"user_id": str(user_a.id)}, secret="test-key")
    cookie_b = sign_cookie({"user_id": str(user_b.id)}, secret="test-key")
    with TestClient(app) as client:
        target = client.get(
            "/api/v1/unsubscribes",
            cookies={SESSION_COOKIE_NAME: cookie_b},
        ).json()["suggestions"][0]
        cross = client.post(
            f"/api/v1/unsubscribes/{target['id']}/dismiss",
            cookies={SESSION_COOKIE_NAME: cookie_a},
        )
        assert cross.status_code == 404


@pytest.mark.asyncio
async def test_hygiene_stats_returns_counters_and_top_domains(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    user, account = await _seed_user(api_session, email="me@x.example")
    await _write_suggestion(
        api_session,
        user=user,
        account=account,
        sender_email="a@dom-a.example",
        sender_domain="dom-a.example",
        confidence=Decimal("0.90"),
        frequency=20,
    )
    await _write_suggestion(
        api_session,
        user=user,
        account=account,
        sender_email="b@dom-a.example",
        sender_domain="dom-a.example",
        confidence=Decimal("0.85"),
        frequency=10,
    )
    await _write_suggestion(
        api_session,
        user=user,
        account=account,
        sender_email="c@dom-b.example",
        sender_domain="dom-b.example",
        confidence=Decimal("0.80"),
        frequency=5,
    )

    cookie = sign_cookie({"user_id": str(user.id)}, secret="test-key")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/hygiene/stats",
            cookies={SESSION_COOKIE_NAME: cookie},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total_candidates"] == 3
        assert body["dismissed_count"] == 0
        # avg over 20/10/5 = 11.67
        assert Decimal(body["average_frequency"]) == Decimal("11.67")
        assert body["top_domains"][0]["sender_domain"] == "dom-a.example"
        assert body["top_domains"][0]["frequency_30d"] == 30


@pytest.mark.asyncio
async def test_unsubscribes_endpoint_requires_session(
    api_session: async_sessionmaker[AsyncSession],
) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/unsubscribes")
        assert response.status_code == 401
        response2 = client.get("/api/v1/hygiene/stats")
        assert response2.status_code == 401
