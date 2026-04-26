"""End-to-end classification pipeline test (plan §14 Phase 2).

Verifies:

* rule short-circuit → ``decision_source='rule'``, zero LLM cost;
* LLM path → ``decision_source='model'`` with prompt_call_log row;
* fallback chain on primary failure → ``status='fallback'``;
* rubric version change propagates within one run;
* encrypted reasons roundtrip through :class:`ClassificationsRepo`.
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
    KnownWasteSender,
    PromptCallLog,
    PromptVersion,
    RubricRule,
    User,
)
from app.llm.client import LLMClient, LLMClientConfig
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.services.classification.pipeline import ClassifyInputs, classify_one
from app.services.classification.repository import ClassificationsRepo
from app.services.classification.rubric import RuleEngine
from app.services.prompts.registry import RegisteredPrompt


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


def _call_result(payload: dict[str, Any], provider: str = "gemini") -> LLMCallResult:
    return LLMCallResult(
        payload=payload,
        tokens_in=100,
        tokens_out=10,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost_usd=Decimal("0.001000"),
        latency_ms=77,
        provider=provider,
        model="gemini-1.5-flash",
    )


async def _seed_email(session, user: User) -> tuple[ConnectedAccount, Email]:
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="mbox@x.com",
        status="active",
    )
    session.add(account)
    await session.flush()
    email = Email(
        account_id=account.id,
        gmail_message_id="m-1",
        thread_id="t-1",
        internal_date=datetime.now(tz=UTC),
        from_addr="sender@corp.example",
        to_addrs=[],
        cc_addrs=[],
        subject="Quarterly review",
        snippet="Short snippet.",
        labels=[],
        content_hash=hashlib.sha256(b"x").digest(),
    )
    email.body = EmailContentBlob(
        message_id=email.id,
        storage_backend="pg",
        plain_text_excerpt="This is the long-form body used by the prompt.",
    )
    session.add(email)
    await session.flush()
    return account, email


async def _registered_prompt(session) -> tuple[RegisteredPrompt, uuid.UUID]:
    content = "Triage body {{from_addr}} {{subject}} {{rubric_summary}} {{plain_text_excerpt}}"
    pv = PromptVersion(
        name="triage",
        version=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).digest(),
        model="gemini-1.5-flash",
        params={"temperature": 0.0, "max_tokens": 400},
    )
    session.add(pv)
    await session.flush()
    spec = PromptSpec(
        name="triage",
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.0,
        max_tokens=400,
    )
    entry = RegisteredPrompt(
        spec=spec,
        content_hash=pv.content_hash,
        frontmatter={"id": "triage"},
        source_path=None,
    )
    return entry, pv.id


@pytest.mark.asyncio
async def test_rule_short_circuit_records_rule_source(test_session) -> None:
    user = User(email="me@x.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    engine = RuleEngine(
        user_rules=(),
        seed_waste=(
            KnownWasteSender(
                id=uuid.uuid4(),
                match={"from_email": "sender@corp.example"},
                added_by="seed",
                reason="seed test",
            ),
        ),
    )
    llm = LLMClient(primary=_FakeProvider("gemini", []))
    repo = ClassificationsRepo(cipher=None)

    outcome = await classify_one(
        ClassifyInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            llm=llm,
            repo=repo,
            prompt_version_id=prompt_version_id,
        ),
        session=test_session,
        rule_engine=engine,
    )
    assert outcome.label == "waste"
    assert outcome.decision_source == "rule"
    assert outcome.tokens_in == 0

    row = (
        await test_session.execute(
            select(Classification).where(Classification.email_id == email.id),
        )
    ).scalar_one()
    assert row.label == "waste"
    assert row.decision_source == "rule"

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert len(calls) == 1
    assert calls[0].status == "skipped"


@pytest.mark.asyncio
async def test_llm_path_records_prompt_call_log(test_session) -> None:
    user = User(email="me@x.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    engine = RuleEngine(user_rules=(), seed_waste=())
    primary = _FakeProvider(
        "gemini",
        [
            _call_result(
                {
                    "category": "must_read",
                    "confidence": 0.9,
                    "reasons_short": "direct message",
                    "is_newsletter": False,
                    "is_job_candidate": False,
                },
            ),
        ],
    )
    llm = LLMClient(primary=primary)
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    repo = ClassificationsRepo(cipher=cipher)

    outcome = await classify_one(
        ClassifyInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            llm=llm,
            repo=repo,
            prompt_version_id=prompt_version_id,
        ),
        session=test_session,
        rule_engine=engine,
    )
    assert outcome.label == "must_read"
    assert outcome.decision_source == "model"
    assert outcome.tokens_in == 100

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert len(calls) == 1
    assert calls[0].status == "ok"
    assert calls[0].tokens_in == 100

    row = (
        await test_session.execute(
            select(Classification).where(Classification.email_id == email.id),
        )
    ).scalar_one()
    assert row.reasons_ct is not None
    reasons = repo.decrypt_reasons(row=row, user_id=user.id)
    model_reasons = reasons["model_reasons"]
    assert isinstance(model_reasons, str)
    assert model_reasons.startswith("direct")


@pytest.mark.asyncio
async def test_low_confidence_demoted_to_needs_review(test_session) -> None:
    user = User(email="me@x.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    primary = _FakeProvider(
        "gemini",
        [
            _call_result(
                {
                    "category": "must_read",
                    "confidence": 0.3,
                    "reasons_short": "unsure",
                },
            ),
        ],
    )
    llm = LLMClient(primary=primary)
    outcome = await classify_one(
        ClassifyInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            llm=llm,
            repo=ClassificationsRepo(cipher=None),
            prompt_version_id=prompt_version_id,
        ),
        session=test_session,
        rule_engine=RuleEngine(user_rules=(), seed_waste=()),
    )
    assert outcome.label == "needs_review"


@pytest.mark.asyncio
async def test_fallback_records_fallback_status(test_session) -> None:
    user = User(email="me@x.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    primary = _FakeProvider(
        "gemini",
        [LLMProviderError("rate limited", retryable=False)],
    )
    fallback = _FakeProvider(
        "anthropic_direct",
        [
            _call_result(
                {
                    "category": "good_to_read",
                    "confidence": 0.7,
                    "reasons_short": "fallback used",
                },
                provider="anthropic_direct",
            ),
        ],
    )
    llm = LLMClient(
        primary=primary,
        fallbacks=(fallback,),
        config=LLMClientConfig(max_retries=1, base_backoff_seconds=0.0),
    )
    outcome = await classify_one(
        ClassifyInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            llm=llm,
            repo=ClassificationsRepo(cipher=None),
            prompt_version_id=prompt_version_id,
        ),
        session=test_session,
        rule_engine=RuleEngine(user_rules=(), seed_waste=()),
    )
    assert outcome.label == "good_to_read"

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert any(c.status == "fallback" for c in calls)


@pytest.mark.asyncio
async def test_rubric_change_propagates_next_run(test_session) -> None:
    user = User(email="me@x.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_email(test_session, user)
    registered, prompt_version_id = await _registered_prompt(test_session)

    initial_rule = RubricRule(
        user_id=user.id,
        priority=500,
        match={"from_email": "sender@corp.example"},
        action={"label": "good_to_read", "confidence": 0.8},
        version=1,
        active=True,
    )
    test_session.add(initial_rule)
    await test_session.flush()

    llm = LLMClient(primary=_FakeProvider("gemini", []))
    repo = ClassificationsRepo(cipher=None)
    inputs = ClassifyInputs(
        email_id=email.id,
        user_id=user.id,
        prompt=registered,
        llm=llm,
        repo=repo,
        prompt_version_id=prompt_version_id,
    )

    outcome_first = await classify_one(inputs, session=test_session)
    assert outcome_first.label == "good_to_read"

    # Mutate the rule → new run should pick up the new verdict.
    initial_rule.action = {"label": "must_read", "confidence": 0.95}
    initial_rule.version = 2
    await test_session.flush()

    outcome_second = await classify_one(inputs, session=test_session)
    assert outcome_second.label == "must_read"
