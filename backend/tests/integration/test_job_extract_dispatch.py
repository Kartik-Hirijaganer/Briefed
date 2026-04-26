"""Integration tests for job-extract queue dispatch + parse (plan §14 Phase 4).

Ensures:

* ``enqueue_unextracted_for_account`` picks job-candidate flagged rows
  that lack a ``job_matches`` row and skips already-extracted ones;
* non-job-candidate rows are ignored;
* ``parse_job_extract_body`` validates :class:`JobExtractMessage`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.db.models import (
    Classification,
    ConnectedAccount,
    Email,
    JobMatch,
    User,
)
from app.services.jobs import (
    enqueue_job_extract_for_email,
    enqueue_unextracted_for_account,
    parse_job_extract_body,
)
from app.workers.messages import JobExtractMessage


class _FakeSqs:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        self.messages.append({"QueueUrl": QueueUrl, "Body": MessageBody})
        return {"MessageId": "fake"}


async def _seed(session) -> tuple[User, ConnectedAccount, list[Email]]:
    user = User(email="me@example.com", tz="UTC", status="active")
    session.add(user)
    await session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="mbox@example.com",
        status="active",
    )
    session.add(account)
    await session.flush()

    emails: list[Email] = []
    classifications = [
        ("good_to_read", True),
        ("good_to_read", True),
        ("must_read", False),
        ("good_to_read", False),
    ]
    for idx, (label, is_job_candidate) in enumerate(classifications):
        email = Email(
            account_id=account.id,
            gmail_message_id=f"m-{idx}",
            thread_id=f"t-{idx}",
            internal_date=datetime.now(tz=UTC),
            from_addr=f"src{idx}@example.com",
            to_addrs=[],
            cc_addrs=[],
            subject=f"subject-{idx}",
            snippet="",
            labels=[],
            content_hash=hashlib.sha256(f"m-{idx}".encode()).digest(),
        )
        session.add(email)
        await session.flush()
        session.add(
            Classification(
                email_id=email.id,
                label=label,
                score=Decimal("0.8"),
                rubric_version=0,
                prompt_version_id=None,
                decision_source="rule",
                model="",
                tokens_in=0,
                tokens_out=0,
                is_job_candidate=is_job_candidate,
                reasons_ct=None,
            ),
        )
        await session.flush()
        emails.append(email)

    # Pre-extract the first job_candidate so the dispatcher skips it.
    session.add(
        JobMatch(
            email_id=emails[0].id,
            title="already",
            company="extracted",
            match_score=Decimal("0.8"),
            match_reason_ct=b"\x00",
            passed_filter=False,
            filter_version=0,
        ),
    )
    await session.flush()
    return user, account, emails


@pytest.mark.asyncio
async def test_enqueue_picks_unextracted_job_candidates(test_session) -> None:
    user, account, _emails = await _seed(test_session)
    sqs = _FakeSqs()

    enqueued = await enqueue_unextracted_for_account(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        queue_url="https://sqs.example/jobs",
        sqs=sqs,
        run_id=None,
    )

    assert enqueued == 1  # one flagged candidate left after skipping the extracted one.
    assert len(sqs.messages) == 1

    body = json.loads(sqs.messages[0]["Body"])
    assert body["kind"] == "job_extract"
    assert body["prompt_name"] == "job_extract"
    assert body["prompt_version"] == 1


@pytest.mark.asyncio
async def test_enqueue_ignores_non_job_rows(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="mbox@example.com",
        status="active",
    )
    test_session.add(account)
    await test_session.flush()

    email = Email(
        account_id=account.id,
        gmail_message_id="m-1",
        thread_id="t-1",
        internal_date=datetime.now(tz=UTC),
        from_addr="src@example.com",
        to_addrs=[],
        cc_addrs=[],
        subject="newsletter",
        snippet="",
        labels=[],
        content_hash=hashlib.sha256(b"m-1").digest(),
    )
    test_session.add(email)
    await test_session.flush()
    test_session.add(
        Classification(
            email_id=email.id,
            label="newsletter",
            score=Decimal("0.8"),
            rubric_version=0,
            prompt_version_id=None,
            decision_source="rule",
            model="",
            tokens_in=0,
            tokens_out=0,
            reasons_ct=None,
        ),
    )
    await test_session.flush()
    sqs = _FakeSqs()

    enqueued = await enqueue_unextracted_for_account(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        queue_url="https://sqs.example/jobs",
        sqs=sqs,
        run_id=None,
    )
    assert enqueued == 0
    assert sqs.messages == []


@pytest.mark.asyncio
async def test_enqueue_job_extract_for_email_targets_single_candidate(test_session) -> None:
    user, account, emails = await _seed(test_session)
    sqs = _FakeSqs()

    enqueued = await enqueue_job_extract_for_email(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        email_id=emails[1].id,
        queue_url="https://sqs.example/jobs",
        sqs=sqs,
        run_id=None,
    )

    assert enqueued == 1
    body = json.loads(sqs.messages[0]["Body"])
    assert body["kind"] == "job_extract"
    assert body["email_id"] == str(emails[1].id)


@pytest.mark.asyncio
async def test_enqueue_job_extract_for_email_skips_ineligible_rows(test_session) -> None:
    user, account, emails = await _seed(test_session)
    sqs = _FakeSqs()

    already_extracted = await enqueue_job_extract_for_email(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        email_id=emails[0].id,
        queue_url="https://sqs.example/jobs",
        sqs=sqs,
        run_id=None,
    )
    not_a_job = await enqueue_job_extract_for_email(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        email_id=emails[2].id,
        queue_url="https://sqs.example/jobs",
        sqs=sqs,
        run_id=None,
    )

    assert already_extracted == 0
    assert not_a_job == 0
    assert sqs.messages == []


def test_parse_job_extract_body_roundtrips() -> None:
    msg = JobExtractMessage(
        user_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
    )
    parsed = parse_job_extract_body(msg.model_dump_json())
    assert isinstance(parsed, JobExtractMessage)
    assert parsed.prompt_name == "job_extract"


def test_parse_job_extract_body_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        parse_job_extract_body("not json")
    with pytest.raises(ValueError):
        # Missing required fields.
        parse_job_extract_body('{"kind": "job_extract"}')
