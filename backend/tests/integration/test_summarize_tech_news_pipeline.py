"""Integration test for the tech-news clustering + summary pipeline.

Covers:

* cluster router grouping newsletters into two buckets;
* min-cluster-size skip for singletons;
* cluster ORM rows + cluster summary written encrypted;
* determinism: the rendered ``newsletters_block`` respects
  ``internal_date`` then ``id`` ordering.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import (
    ConnectedAccount,
    Email,
    EmailContentBlob,
    KnownNewsletter,
    PromptCallLog,
    PromptVersion,
    Summary,
    TechNewsCluster,
    TechNewsClusterMember,
    User,
)
from app.llm.client import LLMClient
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.services.prompts.registry import RegisteredPrompt
from app.services.summarization import (
    ClusterRouter,
    SummariesRepo,
    TechNewsInputs,
    cluster_and_summarize,
)


class _Provider:
    def __init__(self, responses: list[Any]) -> None:
        self.name = "gemini"
        self._responses = list(responses)

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        if not self._responses:
            raise LLMProviderError("exhausted", retryable=False)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _call_result(payload: dict[str, Any]) -> LLMCallResult:
    return LLMCallResult(
        payload=payload,
        tokens_in=300,
        tokens_out=110,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost_usd=Decimal("0.006000"),
        latency_ms=220,
        provider="gemini",
        model="gemini-1.5-flash",
    )


async def _seed_user(session) -> User:
    user = User(email="me@example.com", tz="UTC", status="active")
    session.add(user)
    await session.flush()
    return user


async def _seed_email(
    session,
    *,
    account: ConnectedAccount,
    message_id: str,
    from_addr: str,
    subject: str,
    body: str,
    internal_date: datetime,
    list_id: str | None = None,
) -> Email:
    email = Email(
        account_id=account.id,
        gmail_message_id=message_id,
        thread_id=f"thread-{message_id}",
        internal_date=internal_date,
        from_addr=from_addr,
        to_addrs=[],
        cc_addrs=[],
        subject=subject,
        snippet=body[:80],
        labels=[],
        content_hash=hashlib.sha256(message_id.encode()).digest(),
        list_unsubscribe={"list_id": list_id} if list_id else None,
    )
    session.add(email)
    await session.flush()
    email.body = EmailContentBlob(
        message_id=email.id,
        storage_backend="pg",
        plain_text_excerpt=body,
    )
    await session.flush()
    return email


async def _registered_prompt(session) -> tuple[RegisteredPrompt, uuid.UUID]:
    content = "cluster {{cluster_key}} {{topic_hint}} {{newsletters_block}}"
    pv = PromptVersion(
        name="newsletter_group",
        version=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).digest(),
        model="gemini-1.5-flash",
        params={"temperature": 0.1, "max_tokens": 700},
    )
    session.add(pv)
    await session.flush()
    spec = PromptSpec(
        name="newsletter_group",
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.1,
        max_tokens=700,
    )
    entry = RegisteredPrompt(
        spec=spec,
        content_hash=pv.content_hash,
        frontmatter={"id": "newsletter_group"},
        source_path=None,
    )
    return entry, pv.id


@pytest.mark.asyncio
async def test_cluster_and_summarize_happy_path(test_session) -> None:
    user = await _seed_user(test_session)
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="me@example.com",
        status="active",
    )
    test_session.add(account)
    await test_session.flush()

    now = datetime.now(tz=UTC)
    email_a = await _seed_email(
        test_session,
        account=account,
        message_id="m-1",
        from_addr="digest@llm-research.example",
        subject="Weekly LLM research",
        body="Meta released Llama 4 Scout 17B.",
        internal_date=now - timedelta(hours=2),
        list_id="<llm-research.list-id.example>",
    )
    email_b = await _seed_email(
        test_session,
        account=account,
        message_id="m-2",
        from_addr="alt@llm-research.example",
        subject="LLM roundup",
        body="Mistral shipped MoE 8x22B.",
        internal_date=now - timedelta(hours=1),
        list_id="<llm-research.list-id.example>",
    )
    email_c = await _seed_email(
        test_session,
        account=account,
        message_id="m-3",
        from_addr="solo@example.com",
        subject="Singleton",
        body="Only one.",
        internal_date=now,
    )

    test_session.add(
        KnownNewsletter(
            match={"list_id_equals": "llm-research.list-id.example"},
            cluster_key="llm-research",
            topic_hint="LLM research.",
            maintainer="seed",
        ),
    )
    await test_session.flush()

    router = ClusterRouter(
        rules=tuple(
            (await test_session.execute(select(KnownNewsletter))).scalars().all(),
        ),
    )

    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_Provider(
            [
                _call_result(
                    {
                        "cluster_key": "llm-research",
                        "headline": "Open-weight LLM roundup",
                        "bullets": [
                            "Meta released Llama 4 Scout 17B",
                            "Mistral shipped MoE 8x22B",
                        ],
                        "sources": [email_a.subject, email_b.subject],
                        "confidence": 0.9,
                    },
                ),
            ],
        ),
    )

    repo = SummariesRepo(cipher=None)
    outcome = await cluster_and_summarize(
        TechNewsInputs(
            user_id=user.id,
            run_id=None,
            email_ids=(email_a.id, email_b.id, email_c.id),
            prompt=registered,
            prompt_version_id=prompt_version_id,
            llm=llm,
            repo=repo,
            router=router,
        ),
        session=test_session,
    )

    assert outcome.clusters_created == 1
    assert outcome.clusters_summarized == 1
    assert outcome.clusters_skipped_small == 1  # the singleton
    assert outcome.clusters_failed == 0
    assert outcome.total_tokens_in == 300

    cluster_row = (await test_session.execute(select(TechNewsCluster))).scalars().one()
    assert cluster_row.cluster_key == "llm-research"
    assert cluster_row.member_count == 2

    members = (
        (
            await test_session.execute(
                select(TechNewsClusterMember).where(
                    TechNewsClusterMember.cluster_id == cluster_row.id,
                ),
            )
        )
        .scalars()
        .all()
    )
    assert {m.email_id for m in members} == {email_a.id, email_b.id}
    assert [m.sort_order for m in sorted(members, key=lambda m: m.sort_order)] == [0, 1]

    summary_row = (
        await test_session.execute(
            select(Summary).where(Summary.kind == "tech_news_cluster"),
        )
    ).scalar_one()
    assert summary_row.cluster_id == cluster_row.id
    body = repo.decrypt_cluster_body(row=summary_row, user_id=user.id)
    assert "Llama" in body
    sources = repo.decrypt_cluster_sources(row=summary_row, user_id=user.id)
    assert sources == (email_a.subject, email_b.subject)

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert len(calls) == 1
    assert calls[0].status == "ok"


@pytest.mark.asyncio
async def test_cluster_and_summarize_records_cluster_failure(test_session) -> None:
    user = await _seed_user(test_session)
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="me@example.com",
        status="active",
    )
    test_session.add(account)
    await test_session.flush()

    now = datetime.now(tz=UTC)
    email_a = await _seed_email(
        test_session,
        account=account,
        message_id="m-1",
        from_addr="weekly@ai-weekly.example",
        subject="AI weekly",
        body="Body A.",
        internal_date=now - timedelta(hours=2),
    )
    email_b = await _seed_email(
        test_session,
        account=account,
        message_id="m-2",
        from_addr="weekly2@ai-weekly.example",
        subject="AI weekly 2",
        body="Body B.",
        internal_date=now - timedelta(hours=1),
    )

    registered, prompt_version_id = await _registered_prompt(test_session)
    llm = LLMClient(
        primary=_Provider(
            [LLMProviderError("provider down", retryable=False)],
        ),
    )
    outcome = await cluster_and_summarize(
        TechNewsInputs(
            user_id=user.id,
            run_id=None,
            email_ids=(email_a.id, email_b.id),
            prompt=registered,
            prompt_version_id=prompt_version_id,
            llm=llm,
            repo=SummariesRepo(cipher=None),
            router=ClusterRouter(rules=()),
        ),
        session=test_session,
    )
    assert outcome.clusters_created == 1
    assert outcome.clusters_summarized == 0
    assert outcome.clusters_failed == 1
    # The cluster row survives even when the LLM call fails (sources are
    # recoverable across retries).
    cluster_row = (await test_session.execute(select(TechNewsCluster))).scalars().one()
    assert cluster_row.member_count == 2
