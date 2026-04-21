"""Integration tests for the Phase 5 hygiene aggregate (plan §14 Phase 5).

Covers:

* ``aggregate_sender_stats`` computes frequency / engagement / waste
  correctly on a multi-sender fixture.
* ``rank_senders`` emits a rule-only row when all three criteria fire,
  a model-backed row when the LLM recommends, and a skipped row when
  the criteria fail to clear the 2-of-3 bar.
* LLM veto flips ``confidence`` below the policy gate so the UI hides
  the row even though it is persisted for audit.
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
    Email,
    PromptVersion,
    UnsubscribeSuggestion,
    User,
)
from app.llm.client import LLMClient
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.services.prompts.registry import PromptRegistry, RegisteredPrompt
from app.services.unsubscribe.aggregator import (
    aggregate_sender_stats,
    rank_senders,
    score_sender,
)
from app.services.unsubscribe.repository import UnsubscribeSuggestionsRepo


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
        tokens_in=90,
        tokens_out=30,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost_usd=Decimal("0.000500"),
        latency_ms=110,
        provider="gemini",
        model="gemini-1.5-flash",
    )


async def _seed_account(session) -> tuple[User, ConnectedAccount]:
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
    return user, account


async def _seed_email(
    session,
    *,
    account_id: uuid.UUID,
    gmail_id: str,
    from_addr: str,
    subject: str,
    days_ago: int,
    label: str,
    has_unsub: bool = False,
) -> Email:
    email = Email(
        account_id=account_id,
        gmail_message_id=gmail_id,
        thread_id=f"t-{gmail_id}",
        internal_date=datetime.now(tz=UTC) - timedelta(days=days_ago),
        from_addr=from_addr,
        to_addrs=[],
        cc_addrs=[],
        subject=subject,
        snippet="",
        labels=[],
        list_unsubscribe=(
            {
                "http_urls": [f"https://{from_addr.rsplit('@', maxsplit=1)[-1]}/unsub"],
                "mailto": None,
                "one_click": True,
            }
            if has_unsub
            else None
        ),
        content_hash=hashlib.sha256(gmail_id.encode()).digest(),
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
            reasons_ct=None,
        ),
    )
    await session.flush()
    return email


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
    registry = PromptRegistry({(entry.spec.name, entry.spec.version): entry})
    return registry, pv


@pytest.mark.asyncio
async def test_aggregate_computes_per_sender_metrics(test_session) -> None:
    _user, account = await _seed_account(test_session)
    # Sender A: 6 emails, 5 waste, 1 positive → disengaged, noisy, high waste
    for idx in range(6):
        await _seed_email(
            test_session,
            account_id=account.id,
            gmail_id=f"a-{idx}",
            from_addr="deals@promo.example",
            subject=f"Deal {idx}",
            days_ago=idx,
            label="must_read" if idx == 0 else "waste",
            has_unsub=True,
        )
    # Sender B: 2 emails, 0 waste, 2 must_read
    for idx in range(2):
        await _seed_email(
            test_session,
            account_id=account.id,
            gmail_id=f"b-{idx}",
            from_addr="boss@work.example",
            subject="Update",
            days_ago=idx,
            label="must_read",
        )

    stats = await aggregate_sender_stats(
        session=test_session,
        account_id=account.id,
    )
    assert len(stats) == 2
    promo = next(s for s in stats if s.sender_email == "deals@promo.example")
    work = next(s for s in stats if s.sender_email == "boss@work.example")

    assert promo.frequency_30d == 6
    assert promo.positive_count == 1
    assert promo.waste_count == 5
    assert promo.engagement_score == Decimal("0.167")
    assert promo.waste_rate == Decimal("0.833")
    assert promo.list_unsubscribe is not None
    assert promo.list_unsubscribe.one_click is True

    assert work.frequency_30d == 2
    assert work.engagement_score == Decimal("1.000")
    assert work.waste_rate == Decimal("0.000")

    promo_score = score_sender(promo)
    assert promo_score.hit_count == 3

    work_score = score_sender(work)
    assert work_score.hit_count == 0


@pytest.mark.asyncio
async def test_rank_senders_writes_rule_and_model_rows(test_session) -> None:
    user, account = await _seed_account(test_session)
    # Sender A — all 3 criteria → rule-only row.
    for idx in range(8):
        await _seed_email(
            test_session,
            account_id=account.id,
            gmail_id=f"a-{idx}",
            from_addr="deals@promo.example",
            subject=f"50% off today {idx}",
            days_ago=idx,
            label="waste",
            has_unsub=True,
        )
    # Sender B — 2 of 3 criteria (noisy + low_value, engagement above ceiling).
    for idx in range(6):
        label = "good_to_read" if idx < 2 else "waste"
        await _seed_email(
            test_session,
            account_id=account.id,
            gmail_id=f"b-{idx}",
            from_addr="weekly@news.example",
            subject=f"Weekly digest {idx}",
            days_ago=idx,
            label=label,
            has_unsub=True,
        )
    # Sender C — single hit (noisy but engaged and low waste).
    for idx in range(6):
        await _seed_email(
            test_session,
            account_id=account.id,
            gmail_id=f"c-{idx}",
            from_addr="newsletter@friend.example",
            subject=f"Friendly note {idx}",
            days_ago=idx,
            label="must_read",
            has_unsub=True,
        )

    registry, pv = await _register_prompt(test_session)
    llm = LLMClient(
        primary=_StubProvider(
            [
                _ok_result(
                    {
                        "should_recommend": True,
                        "confidence": 0.86,
                        "category": "newsletter",
                        "rationale": "Noisy weekly digest with 33% engagement.",
                    },
                ),
            ],
        ),
    )
    repo = UnsubscribeSuggestionsRepo(cipher=None)

    outcome = await rank_senders(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        llm=llm,
        prompt=registry.get("unsubscribe_borderline", version=1),
        prompt_version_id=pv.id,
        repo=repo,
    )

    assert outcome.candidates == 3
    assert outcome.rule_recommendations == 1
    assert outcome.model_recommendations == 1
    assert outcome.skipped == 1
    assert outcome.llm_errors == 0

    rows = (await test_session.execute(select(UnsubscribeSuggestion))).scalars().all()
    assert {r.sender_email for r in rows} == {
        "deals@promo.example",
        "weekly@news.example",
    }
    rule_row = next(r for r in rows if r.sender_email == "deals@promo.example")
    model_row = next(r for r in rows if r.sender_email == "weekly@news.example")
    assert rule_row.decision_source == "rule"
    assert rule_row.confidence == Decimal("0.900")
    assert "unsubscribe criteria" in repo.decrypt_rationale(
        row=rule_row,
        user_id=user.id,
    )
    assert model_row.decision_source == "model"
    assert model_row.confidence == Decimal("0.860")
    assert repo.decrypt_rationale(row=model_row, user_id=user.id) == (
        "Noisy weekly digest with 33% engagement."
    )


@pytest.mark.asyncio
async def test_rank_senders_llm_veto_caps_confidence(test_session) -> None:
    user, account = await _seed_account(test_session)
    # 7 emails → noisy; 2 must_read + 5 waste → engagement 0.286 (> 0.2,
    # so `disengaged` does NOT fire), waste_rate 0.714 (>= 0.5 → low_value).
    # That is exactly 2-of-3 → borderline → LLM is called.
    for idx in range(7):
        label = "must_read" if idx < 2 else "waste"
        await _seed_email(
            test_session,
            account_id=account.id,
            gmail_id=f"x-{idx}",
            from_addr="no-reply@bank.example",
            subject=f"Statement {idx}",
            days_ago=idx,
            label=label,
            has_unsub=False,
        )

    registry, pv = await _register_prompt(test_session)
    llm = LLMClient(
        primary=_StubProvider(
            [
                _ok_result(
                    {
                        "should_recommend": False,
                        "confidence": 0.88,
                        "category": "notification",
                        "rationale": "Banking notifications — keep subscribed.",
                    },
                ),
            ],
        ),
    )
    repo = UnsubscribeSuggestionsRepo(cipher=None)
    outcome = await rank_senders(
        session=test_session,
        user_id=user.id,
        account_id=account.id,
        llm=llm,
        prompt=registry.get("unsubscribe_borderline", version=1),
        prompt_version_id=pv.id,
        repo=repo,
    )
    assert outcome.model_recommendations == 1
    row = (await test_session.execute(select(UnsubscribeSuggestion))).scalars().first()
    assert row is not None
    assert row.decision_source == "model"
    # LLM vetoed → confidence capped below the 0.8 policy gate.
    assert row.confidence <= Decimal("0.200")
