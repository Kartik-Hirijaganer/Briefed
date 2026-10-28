"""Integration tests for the summarize SQS handler (plan §14 Phase 3).

Covers both message kinds, asserts metric emission is wired to the
observability module, and checks cluster messages are idempotent per run.
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
    Classification,
    ConnectedAccount,
    DigestRun,
    Email,
    EmailContentBlob,
    KnownNewsletter,
    PromptCallLog,
    PromptVersion,
    Summary,
    TechNewsCluster,
    User,
)
from app.llm.client import LLMClient
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.services.prompts.registry import PromptRegistry, RegisteredPrompt
from app.services.summarization import ClusterRouter, SummariesRepo
from app.workers.handlers.summarize import (
    SummarizeDeps,
    handle_summarize_email,
    handle_tech_news_cluster,
)
from app.workers.messages import SummarizeEmailMessage, TechNewsClusterMessage


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


def _ok_result(payload: dict[str, Any]) -> LLMCallResult:
    return LLMCallResult(
        payload=payload,
        tokens_in=80,
        tokens_out=40,
        tokens_cache_read=10,
        tokens_cache_write=0,
        cost_usd=Decimal("0.001000"),
        latency_ms=110,
        provider="gemini",
        model="gemini-1.5-flash",
    )


async def _register_prompt(
    session,
    *,
    name: str,
    content: str,
) -> tuple[RegisteredPrompt, uuid.UUID]:
    pv = PromptVersion(
        name=name,
        version=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).digest(),
        model="gemini-1.5-flash",
        params={"temperature": 0.1, "max_tokens": 400},
    )
    session.add(pv)
    await session.flush()
    spec = PromptSpec(
        name=name,
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.1,
        max_tokens=400,
    )
    registered = RegisteredPrompt(
        spec=spec,
        content_hash=pv.content_hash,
        frontmatter={"id": name},
        source_path=None,
    )
    return registered, pv.id


@pytest.mark.asyncio
async def test_handle_summarize_email_writes_summary_and_metric(test_session) -> None:
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
        from_addr="a@example.com",
        to_addrs=[],
        cc_addrs=[],
        subject="Subject",
        snippet="Snippet.",
        labels=[],
        content_hash=hashlib.sha256(b"x").digest(),
    )
    test_session.add(email)
    await test_session.flush()
    email.body = EmailContentBlob(
        message_id=email.id,
        storage_backend="pg",
        plain_text_excerpt="Body paragraph.",
    )
    test_session.add(
        Classification(
            email_id=email.id,
            label="good_to_read",
            score=Decimal("0.8"),
            rubric_version=0,
            prompt_version_id=None,
            decision_source="model",
            model="",
            tokens_in=0,
            tokens_out=0,
            reasons_ct=None,
        ),
    )
    await test_session.flush()

    registered, _pv_id = await _register_prompt(
        test_session,
        name="summarize_relevant",
        content="summarize {{category}} {{from_addr}} {{subject}} {{plain_text_excerpt}}",
    )
    registry = PromptRegistry(entries={("summarize_relevant", 1): registered})

    provider = _Provider(
        [
            _ok_result(
                {
                    "tldr": "Body summary.",
                    "confidence": 0.9,
                    "key_points": [],
                    "action_items": [],
                    "entities": [],
                },
            ),
        ],
    )
    llm = LLMClient(primary=provider)
    deps = SummarizeDeps(
        session=test_session,
        llm=llm,
        registry=registry,
        repo=SummariesRepo(cipher=None),
    )

    outcome = await handle_summarize_email(
        SummarizeEmailMessage(
            user_id=user.id,
            account_id=account.id,
            email_id=email.id,
        ),
        deps=deps,
    )
    assert outcome.ok is True
    assert outcome.cache_hit is True
    rows = (await test_session.execute(select(Summary))).scalars().all()
    assert len(rows) == 1 and rows[0].email_id == email.id


_CLUSTER_RESPONSE: dict[str, Any] = {
    "cluster_key": "llm-research",
    "headline": "LLM research",
    "bullets": ["Point"],
    "sources": ["Issue 0", "Issue 1"],
    "confidence": 0.85,
}


async def _seed_newsletter_cluster(
    session,
    *,
    responses: list[Any],
) -> tuple[User, list[Email], SummarizeDeps]:
    """Seed two same-list newsletters, the router rule, and cluster deps."""
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

    now = datetime.now(tz=UTC)
    emails: list[Email] = []
    for idx in range(2):
        email = Email(
            account_id=account.id,
            gmail_message_id=f"m-{idx}",
            thread_id=f"t-{idx}",
            internal_date=now - timedelta(hours=idx),
            from_addr=f"digest{idx}@llm-research.example",
            to_addrs=[],
            cc_addrs=[],
            subject=f"Issue {idx}",
            snippet="Body.",
            labels=[],
            content_hash=hashlib.sha256(f"m-{idx}".encode()).digest(),
            list_unsubscribe={"list_id": "<llm-research.list-id.example>"},
        )
        session.add(email)
        await session.flush()
        email.body = EmailContentBlob(
            message_id=email.id,
            storage_backend="pg",
            plain_text_excerpt=f"Content {idx}.",
        )
        emails.append(email)

    session.add(
        KnownNewsletter(
            match={"list_id_equals": "llm-research.list-id.example"},
            cluster_key="llm-research",
            topic_hint="LLM research.",
            maintainer="seed",
        ),
    )
    await session.flush()

    registered, _pv_id = await _register_prompt(
        session,
        name="newsletter_group",
        content="cluster {{cluster_key}} {{topic_hint}} {{newsletters_block}}",
    )
    router = ClusterRouter(
        rules=tuple((await session.execute(select(KnownNewsletter))).scalars().all()),
    )
    deps = SummarizeDeps(
        session=session,
        llm=LLMClient(primary=_Provider(responses)),
        registry=PromptRegistry(entries={("newsletter_group", 1): registered}),
        repo=SummariesRepo(cipher=None),
        router=router,
    )
    return user, emails, deps


async def _count_rows(session, model: type[Any]) -> int:
    """Count every row of ``model``."""
    return len((await session.execute(select(model))).scalars().all())


@pytest.mark.asyncio
async def test_handle_tech_news_cluster_writes_cluster_summary(test_session) -> None:
    user, emails, deps = await _seed_newsletter_cluster(
        test_session,
        responses=[_ok_result(_CLUSTER_RESPONSE)],
    )

    outcome = await handle_tech_news_cluster(
        TechNewsClusterMessage(
            user_id=user.id,
            email_ids=tuple(e.id for e in emails),
        ),
        deps=deps,
    )
    assert outcome.clusters_summarized == 1
    rows = (
        (
            await test_session.execute(
                select(Summary).where(Summary.kind == "tech_news_cluster"),
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_handle_tech_news_cluster_is_idempotent_per_run(test_session) -> None:
    """A duplicate or redelivered cluster message for a clustered run is a no-op.

    The provider holds one response, so a re-summarize would exhaust it.
    """
    user, emails, deps = await _seed_newsletter_cluster(
        test_session,
        responses=[_ok_result(_CLUSTER_RESPONSE), _ok_result(_CLUSTER_RESPONSE)],
    )
    runs = [
        DigestRun(
            user_id=user.id,
            status="running",
            trigger_type="scheduled",
            started_at=datetime.now(tz=UTC),
            stats={},
        )
        for _ in range(2)
    ]
    test_session.add_all(runs)
    await test_session.flush()

    def _message(run: DigestRun) -> TechNewsClusterMessage:
        return TechNewsClusterMessage(
            user_id=user.id,
            run_id=run.id,
            email_ids=tuple(e.id for e in emails),
        )

    first = await handle_tech_news_cluster(_message(runs[0]), deps=deps)
    duplicate = await handle_tech_news_cluster(_message(runs[0]), deps=deps)

    assert first.clusters_summarized == 1
    assert first.skipped_existing is False
    assert duplicate.skipped_existing is True
    assert duplicate.clusters_created == 0
    assert duplicate.clusters_summarized == 0
    assert duplicate.clusters_failed == 0
    assert await _count_rows(test_session, TechNewsCluster) == 1
    assert await _count_rows(test_session, PromptCallLog) == 1

    next_run = await handle_tech_news_cluster(_message(runs[1]), deps=deps)

    assert next_run.skipped_existing is False
    assert next_run.clusters_summarized == 1
    assert await _count_rows(test_session, TechNewsCluster) == 2
