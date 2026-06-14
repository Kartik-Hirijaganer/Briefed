"""Tests for the fan-out handler."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.consent import CURRENT_PRIVACY_POLICY_VERSION, CURRENT_TERMS_VERSION
from app.db.models import ConnectedAccount, DigestRun, User
from app.workers.handlers.fanout import FanoutDeps, parse_ingest_body, run_fanout
from app.workers.messages import IngestMessage


class _FakeSqs:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        self.sent.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": str(len(self.sent))}


async def _seed(
    session: AsyncSession,
    *,
    count: int = 3,
    accepted: bool = True,
) -> list[ConnectedAccount]:
    """Insert one scheduled user with connected accounts.

    Args:
        session: Active async database session.
        count: Number of accounts to insert.
        accepted: Whether to seed current legal consent.

    Returns:
        Connected account rows for the seeded user.
    """
    user = User(
        email="o@x.com",
        tz="UTC",
        status="active",
        schedule_frequency="once_daily",
        schedule_times_local=["08:00"],
        schedule_timezone="UTC",
    )
    if accepted:
        user.privacy_policy_version_accepted = CURRENT_PRIVACY_POLICY_VERSION
        user.terms_version_accepted = CURRENT_TERMS_VERSION
    session.add(user)
    await session.flush()
    accounts: list[ConnectedAccount] = []
    for i in range(count):
        account = ConnectedAccount(
            user_id=user.id,
            provider="gmail",
            email=f"a{i}@x.com",
            status="active",
            auto_scan_enabled=(i != 1),  # flip one off so filter bites
        )
        session.add(account)
        accounts.append(account)
    await session.commit()
    return accounts


async def test_fanout_enqueues_only_auto_scan_accounts(
    test_session: AsyncSession,
) -> None:
    accounts = await _seed(test_session)
    sqs = _FakeSqs()
    deps = FanoutDeps(
        session=test_session,
        sqs=sqs,
        ingest_queue_url="https://sqs.local/ingest",
    )
    # Track C — Phase II.4: a user only fans out when ``is_due``. Pin
    # the clock inside the 08:00 ±7:30 slot window so the user is
    # eligible; the auto_scan filter still skips one of three accounts.
    with patch(
        "app.workers.handlers.fanout.utcnow",
        return_value=datetime(2026, 4, 25, 8, 5, tzinfo=ZoneInfo("UTC")),
    ):
        enqueued = await run_fanout(deps=deps)
    assert enqueued == 2
    assert len(sqs.sent) == 2
    runs = (await test_session.execute(select(DigestRun))).scalars().all()
    assert len(runs) == 1
    assert runs[0].trigger_type == "scheduled"
    assert runs[0].status == "queued"
    assert runs[0].stats["account_ids"] == [str(accounts[0].id), str(accounts[2].id)]
    payload = parse_ingest_body(sqs.sent[0]["MessageBody"])
    assert payload.run_id == runs[0].id


async def test_fanout_skips_user_without_legal_consent(
    test_session: AsyncSession,
) -> None:
    """Scheduled fanout must not enqueue accounts for unconsented users."""
    await _seed(test_session, accepted=False)
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


async def test_parse_ingest_body_roundtrips() -> None:
    original = IngestMessage(user_id=uuid4(), account_id=uuid4())
    body = original.model_dump_json()
    reparsed = parse_ingest_body(body)
    assert reparsed.user_id == original.user_id


async def test_parse_ingest_body_rejects_bad_json() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_ingest_body("{not json")
