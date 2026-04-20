"""End-to-end per-email summarizer test (plan §14 Phase 3).

Covers:

* happy path → ``summaries`` row written with encrypted body + entities;
  ``prompt_call_log`` row populated;
* cache-hit path → ``cache_hit=True`` recorded when the provider
  reports cache-read tokens;
* schema-mismatch path → the fallback provider recovers and the row is
  still persisted with ``fallback_used=True``.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.core.security import EnvelopeCipher
from app.db.models import (
    Classification,
    ConnectedAccount,
    Email,
    EmailContentBlob,
    PromptCallLog,
    PromptVersion,
    Summary,
    User,
)
from app.llm.client import LLMClient
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.services.prompts.registry import RegisteredPrompt
from app.services.summarization import (
    SummariesRepo,
    SummarizeInputs,
    summarize_email,
)


class _FakeKms:
    def __init__(self) -> None:
        self._master = b"M" * 32

    def encrypt(self, **kwargs: Any) -> dict[str, Any]:
        pt = kwargs["Plaintext"]
        wrapped = bytes(b ^ m for b, m in zip(pt, self._master, strict=True))
        return {"CiphertextBlob": len(pt).to_bytes(2, "big") + wrapped}

    def decrypt(self, **kwargs: Any) -> dict[str, Any]:
        blob = kwargs["CiphertextBlob"]
        length = int.from_bytes(blob[:2], "big")
        wrapped = blob[2:]
        pt = bytes(b ^ m for b, m in zip(wrapped, self._master, strict=True))
        assert len(pt) == length
        return {"Plaintext": pt}


class _FakeProvider:
    def __init__(self, name: str, responses: list[Any]) -> None:
        self.name = name
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


def _call_result(
    payload: dict[str, Any],
    *,
    provider: str = "gemini",
    tokens_in: int = 120,
    tokens_out: int = 60,
    cache_read: int = 0,
) -> LLMCallResult:
    return LLMCallResult(
        payload=payload,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_cache_read=cache_read,
        tokens_cache_write=0,
        cost_usd=Decimal("0.002500"),
        latency_ms=185,
        provider=provider,
        model="gemini-1.5-flash",
    )


async def _seed_email(session, user: User) -> tuple[ConnectedAccount, Email]:
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
        from_addr="cofounder@startup.example",
        to_addrs=[],
        cc_addrs=[],
        subject="Quarterly review",
        snippet="Short snippet.",
        labels=[],
        content_hash=hashlib.sha256(b"x").digest(),
    )
    session.add(email)
    await session.flush()
    email.body = EmailContentBlob(
        message_id=email.id,
        storage_backend="pg",
        plain_text_excerpt="We need to confirm the 10a Pacific call tomorrow.",
    )
    session.add(
        Classification(
            email_id=email.id,
            label="must_read",
            score=Decimal("0.9"),
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
    return account, email


async def _registered_prompt(session) -> tuple[RegisteredPrompt, uuid.UUID]:
    content = "summarize {{category}} {{from_addr}} {{subject}} {{plain_text_excerpt}}"
    pv = PromptVersion(
        name="summarize_relevant",
        version=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).digest(),
        model="gemini-1.5-flash",
        params={"temperature": 0.1, "max_tokens": 600},
    )
    session.add(pv)
    await session.flush()
    spec = PromptSpec(
        name="summarize_relevant",
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.1,
        max_tokens=600,
    )
    entry = RegisteredPrompt(
        spec=spec,
        content_hash=pv.content_hash,
        frontmatter={"id": "summarize_relevant"},
        source_path=None,
    )
    return entry, pv.id


@pytest.mark.asyncio
async def test_summarize_email_happy_path(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_FakeProvider(
            "gemini",
            [
                _call_result(
                    {
                        "tldr": "Cofounder asks to confirm the 10a PT call.",
                        "key_points": ["10a PT call"],
                        "action_items": ["Confirm the call"],
                        "entities": ["cofounder"],
                        "confidence": 0.88,
                    },
                ),
            ],
        ),
    )
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    repo = SummariesRepo(cipher=cipher)

    outcome = await summarize_email(
        SummarizeInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            prompt_version_id=prompt_version_id,
            llm=llm,
            repo=repo,
        ),
        session=test_session,
    )
    assert outcome.ok is True
    assert outcome.confidence == pytest.approx(0.88)
    assert outcome.cache_hit is False

    row = (
        await test_session.execute(
            select(Summary).where(Summary.email_id == email.id),
        )
    ).scalar_one()
    assert row.kind == "email"
    assert row.body_md_ct  # non-empty ciphertext
    body = repo.decrypt_email_body(row=row, user_id=user.id)
    assert "10a PT call" in body
    entities = repo.decrypt_email_entities(row=row, user_id=user.id)
    assert entities == ("cofounder",)

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert len(calls) == 1
    assert calls[0].status == "ok"
    assert calls[0].tokens_in == 120


@pytest.mark.asyncio
async def test_summarize_email_records_cache_hit(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_FakeProvider(
            "gemini",
            [
                _call_result(
                    {
                        "tldr": "ok",
                        "key_points": [],
                        "action_items": [],
                        "entities": [],
                        "confidence": 0.9,
                    },
                    cache_read=90,
                ),
            ],
        ),
    )

    outcome = await summarize_email(
        SummarizeInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            prompt_version_id=prompt_version_id,
            llm=llm,
            repo=SummariesRepo(cipher=None),
        ),
        session=test_session,
    )
    assert outcome.cache_hit is True
    row = (
        await test_session.execute(
            select(Summary).where(Summary.email_id == email.id),
        )
    ).scalar_one()
    assert row.cache_hit is True


@pytest.mark.asyncio
async def test_summarize_email_fallback_used(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    primary = _FakeProvider(
        "gemini",
        [LLMProviderError("bad body", retryable=False)],
    )
    fallback = _FakeProvider(
        "anthropic_direct",
        [
            _call_result(
                {
                    "tldr": "Fallback worked.",
                    "confidence": 0.7,
                    "key_points": [],
                    "action_items": [],
                    "entities": [],
                },
                provider="anthropic_direct",
            ),
        ],
    )
    llm = LLMClient(primary=primary, fallbacks=(fallback,))

    outcome = await summarize_email(
        SummarizeInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            prompt_version_id=prompt_version_id,
            llm=llm,
            repo=SummariesRepo(cipher=None),
        ),
        session=test_session,
    )
    assert outcome.ok is True
    assert outcome.fallback_used is True

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert any(c.status == "fallback" for c in calls)


@pytest.mark.asyncio
async def test_summarize_email_handles_llm_exhaustion(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_FakeProvider(
            "gemini",
            [LLMProviderError("empty", retryable=False)],
        ),
    )
    outcome = await summarize_email(
        SummarizeInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            prompt_version_id=prompt_version_id,
            llm=llm,
            repo=SummariesRepo(cipher=None),
        ),
        session=test_session,
    )
    assert outcome.ok is False
    assert outcome.skipped_reason
    rows = (await test_session.execute(select(Summary))).scalars().all()
    assert rows == []
    # The error row lands via LLMClient's log_call fallback path.
    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert calls and calls[0].status == "error"
