"""Tests for the classify-dispatch helper (plan §14 Phase 2)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.db.models import (
    Classification,
    ConnectedAccount,
    Email,
    User,
)
from app.services.classification.dispatch import (
    enqueue_unclassified_for_account,
    parse_classify_body,
)
from app.workers.messages import ClassifyMessage


class _FakeSqs:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        self.messages.append((QueueUrl, MessageBody))
        return {"MessageId": str(uuid.uuid4())}


@pytest.mark.asyncio
async def test_enqueue_skips_already_classified(test_session) -> None:
    user = User(email="me@x.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="me@x.com",
        status="active",
    )
    test_session.add(account)
    await test_session.flush()

    email_a = Email(
        account_id=account.id,
        gmail_message_id="a",
        thread_id="t",
        internal_date=datetime.now(tz=UTC),
        from_addr="x@y.com",
        to_addrs=[],
        cc_addrs=[],
        subject="a",
        snippet="",
        labels=[],
        content_hash=hashlib.sha256(b"a").digest(),
    )
    email_b = Email(
        account_id=account.id,
        gmail_message_id="b",
        thread_id="t",
        internal_date=datetime.now(tz=UTC),
        from_addr="x@y.com",
        to_addrs=[],
        cc_addrs=[],
        subject="b",
        snippet="",
        labels=[],
        content_hash=hashlib.sha256(b"b").digest(),
    )
    test_session.add_all([email_a, email_b])
    await test_session.flush()

    # email_a already classified — must be skipped.
    test_session.add(
        Classification(
            email_id=email_a.id,
            label="ignore",
            score=0.5,
            rubric_version=0,
            decision_source="rule",
        ),
    )
    await test_session.flush()

    sqs = _FakeSqs()
    count = await enqueue_unclassified_for_account(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        queue_url="https://sqs.example/classify",
        sqs=sqs,
        run_id=None,
    )
    assert count == 1
    body = json.loads(sqs.messages[0][1])
    assert body["kind"] == "classify"
    assert body["email_id"] == str(email_b.id)


def test_parse_classify_body_roundtrip() -> None:
    payload = ClassifyMessage(
        user_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
    )
    parsed = parse_classify_body(payload.model_dump_json())
    assert parsed == payload


def test_parse_classify_body_rejects_bad_json() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_classify_body("{")


def test_parse_classify_body_rejects_extra() -> None:
    with pytest.raises(ValueError):
        parse_classify_body(
            json.dumps(
                {
                    "kind": "classify",
                    "user_id": str(uuid.uuid4()),
                    "account_id": str(uuid.uuid4()),
                    "email_id": str(uuid.uuid4()),
                    "bogus": 1,
                },
            ),
        )
