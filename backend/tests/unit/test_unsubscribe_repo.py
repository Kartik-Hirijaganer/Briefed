"""Unit tests for :class:`UnsubscribeSuggestionsRepo` (plan §14 Phase 5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.db.models import ConnectedAccount, User
from app.services.unsubscribe.repository import (
    UnsubscribeSuggestionsRepo,
    UnsubscribeSuggestionWrite,
)


async def _seed_account(session) -> tuple[User, ConnectedAccount]:
    user = User(email="me@x.example", tz="UTC", status="active")
    session.add(user)
    await session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="mbox@x.example",
        status="active",
    )
    session.add(account)
    await session.flush()
    return user, account


def _payload(
    *,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    rationale: str,
    confidence: str = "0.900",
    last_email_at: datetime | None = None,
) -> UnsubscribeSuggestionWrite:
    return UnsubscribeSuggestionWrite(
        account_id=account_id,
        user_id=user_id,
        sender_domain="promo.example",
        sender_email="deals@promo.example",
        frequency_30d=22,
        engagement_score=Decimal("0.000"),
        waste_rate=Decimal("0.640"),
        list_unsubscribe={
            "http_urls": ["https://promo.example/u"],
            "mailto": None,
            "one_click": True,
        },
        confidence=Decimal(confidence),
        decision_source="rule",
        rationale=rationale,
        prompt_version_id=None,
        model="",
        tokens_in=0,
        tokens_out=0,
        last_email_at=last_email_at,
    )


@pytest.mark.asyncio
async def test_upsert_inserts_and_replaces(test_session) -> None:
    user, account = await _seed_account(test_session)
    repo = UnsubscribeSuggestionsRepo(cipher=None)

    row = await repo.upsert(
        test_session,
        _payload(
            account_id=account.id,
            user_id=user.id,
            rationale="All three criteria triggered.",
            last_email_at=datetime(2026, 4, 19, 12, 0, tzinfo=UTC),
        ),
    )
    assert repo.decrypt_rationale(row=row, user_id=user.id) == ("All three criteria triggered.")

    # Replace the payload with a new rationale; should reuse same row.
    updated = await repo.upsert(
        test_session,
        _payload(
            account_id=account.id,
            user_id=user.id,
            rationale="Fresh run — confidence dropped slightly.",
            confidence="0.800",
            last_email_at=datetime(2026, 4, 20, 12, 0, tzinfo=UTC),
        ),
    )
    assert updated.id == row.id
    assert repo.decrypt_rationale(row=updated, user_id=user.id) == (
        "Fresh run — confidence dropped slightly."
    )
    assert updated.confidence == Decimal("0.800")


@pytest.mark.asyncio
async def test_upsert_preserves_dismissal(test_session) -> None:
    user, account = await _seed_account(test_session)
    repo = UnsubscribeSuggestionsRepo(cipher=None)

    row = await repo.upsert(
        test_session,
        _payload(
            account_id=account.id,
            user_id=user.id,
            rationale="Noisy promo; recommend unsub.",
        ),
    )

    # Simulate a dismissal flip (API path sets these directly).
    row.dismissed = True
    row.dismissed_at = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await test_session.flush()

    # Re-run the aggregate upsert.
    row_after = await repo.upsert(
        test_session,
        _payload(
            account_id=account.id,
            user_id=user.id,
            rationale="Same sender, fresh run.",
        ),
    )

    assert row_after.id == row.id
    assert row_after.dismissed is True
    assert row_after.dismissed_at == datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
