"""Integration tests for summarize-queue dispatch + parse (plan §14 Phase 3).

Ensures:

* ``enqueue_unsummarized_for_run`` picks must_read / good_to_read rows
  and newsletter-flagged rows that lack a summary;
* newsletter-flagged rows enqueue a single :class:`TechNewsClusterMessage`;
* ``parse_summarize_body`` routes by discriminator.
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
    Summary,
    User,
)
from app.services.summarization import (
    enqueue_summary_for_email,
    enqueue_unsummarized_for_run,
    parse_summarize_body,
)
from app.workers.messages import (
    SummarizeEmailMessage,
    TechNewsClusterMessage,
)


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
        ("must_read", False),
        ("good_to_read", False),
        ("good_to_read", True),
        ("good_to_read", True),
        ("ignore", False),
        ("waste", False),
    ]
    for idx, (label, is_newsletter) in enumerate(classifications):
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
                is_newsletter=is_newsletter,
                reasons_ct=None,
            ),
        )
        await session.flush()
        emails.append(email)

    # Pre-summarize one of the must_read emails so the dispatcher skips it.
    session.add(
        Summary(
            kind="email",
            email_id=emails[0].id,
            cluster_id=None,
            prompt_version_id=None,
            model="gemini-1.5-flash",
            tokens_in=0,
            tokens_out=0,
            body_md_ct=b"\x00",
            entities_ct=None,
            cache_hit=False,
            confidence=Decimal("0.0"),
            batch_id=None,
        ),
    )
    await session.flush()
    return user, account, emails


@pytest.mark.asyncio
async def test_enqueue_skips_already_summarized(test_session) -> None:
    user, account, _emails = await _seed(test_session)
    sqs = _FakeSqs()

    per_email, cluster = await enqueue_unsummarized_for_run(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        queue_url="https://sqs.example/test",
        sqs=sqs,
        run_id=None,
    )

    assert per_email == 3  # good_to_read + 2 newsletter flags; must_read[0] skipped.
    assert cluster == 1  # two newsletters form a cluster.
    assert len(sqs.messages) == 4  # 3 per-email + 1 cluster.

    kinds = [json.loads(m["Body"])["kind"] for m in sqs.messages]
    assert kinds.count("summarize_email") == 3
    assert kinds.count("tech_news_cluster") == 1


@pytest.mark.asyncio
async def test_enqueue_summary_for_email_targets_single_eligible_row(test_session) -> None:
    user, account, emails = await _seed(test_session)
    sqs = _FakeSqs()

    enqueued = await enqueue_summary_for_email(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        email_id=emails[1].id,
        queue_url="https://sqs.example/test",
        sqs=sqs,
        run_id=None,
    )

    assert enqueued == 1
    body = json.loads(sqs.messages[0]["Body"])
    assert body["kind"] == "summarize_email"
    assert body["email_id"] == str(emails[1].id)


@pytest.mark.asyncio
async def test_enqueue_summary_for_email_skips_ineligible_rows(test_session) -> None:
    user, account, emails = await _seed(test_session)
    sqs = _FakeSqs()

    already_summarized = await enqueue_summary_for_email(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        email_id=emails[0].id,
        queue_url="https://sqs.example/test",
        sqs=sqs,
        run_id=None,
    )
    ignored = await enqueue_summary_for_email(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        email_id=emails[4].id,
        queue_url="https://sqs.example/test",
        sqs=sqs,
        run_id=None,
    )

    assert already_summarized == 0
    assert ignored == 0
    assert sqs.messages == []


@pytest.mark.asyncio
async def test_parse_summarize_body_discriminates() -> None:
    per_email_msg = SummarizeEmailMessage(
        user_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
    )
    cluster_msg = TechNewsClusterMessage(
        user_id=uuid.uuid4(),
        email_ids=(uuid.uuid4(), uuid.uuid4()),
    )

    parsed_email = parse_summarize_body(per_email_msg.model_dump_json())
    parsed_cluster = parse_summarize_body(cluster_msg.model_dump_json())
    assert isinstance(parsed_email, SummarizeEmailMessage)
    assert isinstance(parsed_cluster, TechNewsClusterMessage)


@pytest.mark.asyncio
async def test_parse_summarize_body_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        parse_summarize_body('{"kind": "nope"}')
    with pytest.raises(ValueError):
        parse_summarize_body("not json")
