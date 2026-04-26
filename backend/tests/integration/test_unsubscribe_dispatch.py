"""Integration tests for the unsubscribe SQS dispatch + handler (plan §14 Phase 5)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import (
    Classification,
    ConnectedAccount,
    Email,
    PromptVersion,
    UnsubscribeSuggestion,
    User,
)
from app.llm.client import LLMClient
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.services.prompts.registry import PromptRegistry, RegisteredPrompt
from app.services.unsubscribe import (
    UnsubscribeSuggestionsRepo,
    enqueue_hygiene_run_for_account,
    parse_unsubscribe_body,
)
from app.workers.handlers.unsubscribe import UnsubscribeDeps, handle_unsubscribe
from app.workers.messages import UnsubscribeMessage


class _FakeSqs:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def send_message(
        self,
        *,
        QueueUrl: str,
        MessageBody: str,
    ) -> dict[str, Any]:
        self.messages.append({"QueueUrl": QueueUrl, "Body": MessageBody})
        return {"MessageId": "fake"}


class _StubProvider:
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
        tokens_in=60,
        tokens_out=30,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost_usd=Decimal("0.000500"),
        latency_ms=95,
        provider="gemini",
        model="gemini-1.5-flash",
    )


@pytest.mark.asyncio
async def test_enqueue_hygiene_run_emits_one_message() -> None:
    sqs = _FakeSqs()
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    run_id = uuid.uuid4()
    enqueued = await enqueue_hygiene_run_for_account(
        user_id=user_id,
        account_id=account_id,
        queue_url="https://sqs.example/unsub",
        sqs=sqs,
        run_id=run_id,
    )
    assert enqueued == 1
    assert len(sqs.messages) == 1
    body = json.loads(sqs.messages[0]["Body"])
    assert body["kind"] == "unsubscribe"
    assert body["user_id"] == str(user_id)
    assert body["account_id"] == str(account_id)
    assert body["run_id"] == str(run_id)
    assert body["prompt_name"] == "unsubscribe_borderline"


def test_parse_unsubscribe_body_roundtrips() -> None:
    msg = UnsubscribeMessage(
        user_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
    )
    parsed = parse_unsubscribe_body(msg.model_dump_json())
    assert isinstance(parsed, UnsubscribeMessage)
    assert parsed.prompt_name == "unsubscribe_borderline"
    assert parsed.prompt_version == 1


def test_parse_unsubscribe_body_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        parse_unsubscribe_body("not json")
    with pytest.raises(ValueError):
        parse_unsubscribe_body('{"kind": "unsubscribe"}')


async def _seed(session) -> tuple[User, ConnectedAccount]:
    user = User(email="me@x.example", tz="UTC", status="active")
    session.add(user)
    await session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="mbox@x.example",
        status="active",
    )
    session.add(account)
    await session.flush()
    for idx in range(8):
        email = Email(
            account_id=account.id,
            gmail_message_id=f"m-{idx}",
            thread_id=f"t-{idx}",
            internal_date=datetime.now(tz=UTC) - timedelta(days=idx),
            from_addr="deals@promo.example",
            to_addrs=[],
            cc_addrs=[],
            subject=f"Promo {idx}",
            snippet="",
            labels=[],
            list_unsubscribe={
                "http_urls": ["https://promo.example/u"],
                "mailto": None,
                "one_click": True,
            },
            content_hash=hashlib.sha256(f"m-{idx}".encode()).digest(),
        )
        session.add(email)
        await session.flush()
        session.add(
            Classification(
                email_id=email.id,
                label="waste",
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
        await session.flush()
    return user, account


async def _register_prompt(session) -> tuple[PromptRegistry, PromptVersion]:
    content = (
        "{{sender_email}} {{sender_domain}} {{frequency_30d}}"
        " {{engagement_score}} {{waste_rate}} {{has_list_unsubscribe}}"
        " {{criteria_hit}} {{subject_samples}}"
    )
    pv = PromptVersion(
        name="unsubscribe_borderline",
        version=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).digest(),
        model="gemini-1.5-flash",
        params={"temperature": 0.0, "max_tokens": 200},
    )
    session.add(pv)
    await session.flush()
    spec = PromptSpec(
        name="unsubscribe_borderline",
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.0,
        max_tokens=200,
    )
    entry = RegisteredPrompt(
        spec=spec,
        content_hash=pv.content_hash,
        frontmatter={"id": "unsubscribe_borderline"},
        source_path=None,
    )
    return PromptRegistry({(entry.spec.name, entry.spec.version): entry}), pv


@pytest.mark.asyncio
async def test_handle_unsubscribe_writes_row(test_session) -> None:
    user, account = await _seed(test_session)
    registry, _pv = await _register_prompt(test_session)
    # 3-of-3 criteria → rule path, no LLM call expected.
    deps = UnsubscribeDeps(
        session=test_session,
        llm=LLMClient(primary=_StubProvider([])),
        registry=registry,
        repo=UnsubscribeSuggestionsRepo(cipher=None),
    )
    message = UnsubscribeMessage(user_id=user.id, account_id=account.id)
    outcome = await handle_unsubscribe(message, deps=deps)
    assert outcome.rule_recommendations == 1
    rows = (await test_session.execute(select(UnsubscribeSuggestion))).scalars().all()
    assert len(rows) == 1
    assert rows[0].sender_email == "deals@promo.example"


@pytest.mark.asyncio
async def test_handle_unsubscribe_raises_when_prompt_version_missing(
    test_session,
) -> None:
    user, account = await _seed(test_session)
    # Registry knows the prompt but no DB row.
    content = "no db row"
    spec = PromptSpec(
        name="unsubscribe_borderline",
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.0,
        max_tokens=100,
    )
    entry = RegisteredPrompt(
        spec=spec,
        content_hash=hashlib.sha256(content.encode()).digest(),
        frontmatter={"id": "unsubscribe_borderline"},
        source_path=None,
    )
    registry = PromptRegistry({(entry.spec.name, entry.spec.version): entry})

    deps = UnsubscribeDeps(
        session=test_session,
        llm=LLMClient(primary=_StubProvider([])),
        registry=registry,
        repo=UnsubscribeSuggestionsRepo(cipher=None),
    )
    with pytest.raises(LookupError):
        await handle_unsubscribe(
            UnsubscribeMessage(user_id=user.id, account_id=account.id),
            deps=deps,
        )
