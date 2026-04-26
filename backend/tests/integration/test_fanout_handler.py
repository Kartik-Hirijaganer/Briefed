"""Tests for the fan-out handler."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConnectedAccount, User
from app.workers.handlers.fanout import FanoutDeps, parse_ingest_body, run_fanout
from app.workers.messages import IngestMessage


class _FakeSqs:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        self.sent.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": str(len(self.sent))}


async def _seed(session: AsyncSession, *, count: int = 3) -> list[ConnectedAccount]:
    user = User(
        email="o@x.com",
        tz="UTC",
        status="active",
        schedule_frequency="once_daily",
        schedule_times_local=["08:00"],
        schedule_timezone="UTC",
    )
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
    await _seed(test_session)
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


async def test_parse_ingest_body_roundtrips() -> None:
    original = IngestMessage(user_id=uuid4(), account_id=uuid4())
    body = original.model_dump_json()
    reparsed = parse_ingest_body(body)
    assert reparsed.user_id == original.user_id


async def test_parse_ingest_body_rejects_bad_json() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_ingest_body("{not json")
