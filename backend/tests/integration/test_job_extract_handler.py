"""Integration tests for the job-extract SQS handler (plan §14 Phase 4).

Covers the happy path end-to-end: handler resolves the prompt,
invokes :func:`extract_job`, and persists one :class:`JobMatch` row.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import (
    Classification,
    ConnectedAccount,
    Email,
    EmailContentBlob,
    JobMatch,
    PromptVersion,
    User,
)
from app.llm.client import LLMClient
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.services.jobs.repository import JobMatchesRepo
from app.services.prompts.registry import PromptRegistry, RegisteredPrompt
from app.workers.handlers.jobs import JobExtractDeps, handle_job_extract
from app.workers.messages import JobExtractMessage


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
        tokens_in=160,
        tokens_out=70,
        tokens_cache_read=20,
        tokens_cache_write=0,
        cost_usd=Decimal("0.002000"),
        latency_ms=170,
        provider="gemini",
        model="gemini-1.5-flash",
    )


async def _register_prompt(session) -> tuple[PromptRegistry, PromptVersion]:
    content = "extract {{from_addr}} {{subject}} {{reader_profile}} {{plain_text_excerpt}}"
    pv = PromptVersion(
        name="job_extract",
        version=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).digest(),
        model="gemini-1.5-flash",
        params={"temperature": 0.0, "max_tokens": 500},
    )
    session.add(pv)
    await session.flush()
    spec = PromptSpec(
        name="job_extract",
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.0,
        max_tokens=500,
    )
    entry = RegisteredPrompt(
        spec=spec,
        content_hash=pv.content_hash,
        frontmatter={"id": "job_extract"},
        source_path=None,
    )
    registry = PromptRegistry({(entry.spec.name, entry.spec.version): entry})
    return registry, pv


async def _seed_email(session) -> tuple[User, Email]:
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
    email = Email(
        account_id=account.id,
        gmail_message_id="m-1",
        thread_id="t-1",
        internal_date=datetime.now(tz=UTC),
        from_addr="recruiter@acme.example",
        to_addrs=[],
        cc_addrs=[],
        subject="Staff Backend Engineer @ Acme",
        snippet="",
        labels=[],
        content_hash=hashlib.sha256(b"job").digest(),
    )
    session.add(email)
    await session.flush()
    email.body = EmailContentBlob(
        message_id=email.id,
        storage_backend="pg",
        plain_text_excerpt=(
            "Staff Backend Engineer at Acme. Fully remote in the US. "
            "Comp $210,000-$260,000 plus equity. Apply at https://acme.example/jobs"
        ),
    )
    session.add(
        Classification(
            email_id=email.id,
            label="job_candidate",
            score=Decimal("0.92"),
            rubric_version=0,
            prompt_version_id=None,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=0,
            tokens_out=0,
            reasons_ct=None,
        ),
    )
    await session.flush()
    return user, email


@pytest.mark.asyncio
async def test_handle_job_extract_writes_row(test_session) -> None:
    registry, _pv = await _register_prompt(test_session)
    user, email = await _seed_email(test_session)

    llm = LLMClient(
        primary=_Provider(
            [
                _ok_result(
                    {
                        "title": "Staff Backend Engineer",
                        "company": "Acme",
                        "location": "US",
                        "remote": True,
                        "comp_min": 210_000,
                        "comp_max": 260_000,
                        "currency": "USD",
                        "comp_phrase": "$210,000-$260,000",
                        "seniority": "staff",
                        "source_url": "https://acme.example/jobs",
                        "match_reason": "Remote staff role — strong match.",
                        "confidence": 0.9,
                    },
                ),
            ],
        ),
    )
    deps = JobExtractDeps(
        session=test_session,
        llm=llm,
        registry=registry,
        repo=JobMatchesRepo(cipher=None),
    )

    message = JobExtractMessage(
        user_id=user.id,
        account_id=email.account_id,
        email_id=email.id,
    )
    outcome = await handle_job_extract(message, deps=deps)
    assert outcome.ok is True
    assert outcome.passed_filter is True
    assert outcome.corroborated is True

    rows = (await test_session.execute(select(JobMatch))).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "Staff Backend Engineer"


@pytest.mark.asyncio
async def test_handle_job_extract_raises_when_prompt_version_missing(test_session) -> None:
    user, email = await _seed_email(test_session)

    # Registry knows the prompt but no DB row is inserted.
    content = "no db row"
    spec = PromptSpec(
        name="job_extract",
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.0,
        max_tokens=100,
    )
    entry = RegisteredPrompt(
        spec=spec,
        content_hash=hashlib.sha256(content.encode()).digest(),
        frontmatter={"id": "job_extract"},
        source_path=None,
    )
    registry = PromptRegistry({(entry.spec.name, entry.spec.version): entry})

    deps = JobExtractDeps(
        session=test_session,
        llm=LLMClient(primary=_Provider([])),
        registry=registry,
        repo=JobMatchesRepo(cipher=None),
    )
    message = JobExtractMessage(
        user_id=user.id,
        account_id=email.account_id,
        email_id=email.id,
    )
    with pytest.raises(LookupError):
        await handle_job_extract(message, deps=deps)
