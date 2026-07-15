"""Integration tests for Phase 4 category digest summaries."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.security import EnvelopeCipher
from app.db.models import (
    Classification,
    ConnectedAccount,
    DigestRun,
    DigestRunEmail,
    Email,
    PromptCallLog,
    PromptVersion,
    Summary,
    User,
)
from app.llm.client import LLMClient
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.llm.schemas import CategoryDigestGroup
from app.services.prompts.registry import RegisteredPrompt
from app.services.summarization import (
    CategoryDigestInputs,
    CategoryDigestNotReadyError,
    SummariesRepo,
    SummaryCategoryDigestWrite,
    summarize_category,
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


class _Provider:
    def __init__(self, responses: list[Any]) -> None:
        self.name = "gemini"
        self.calls = 0
        self.prompts: list[str] = []
        self._responses = list(responses)

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        self.calls += 1
        self.prompts.append(rendered_prompt)
        if not self._responses:
            raise LLMProviderError("exhausted", retryable=False)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _call_result(payload: dict[str, Any]) -> LLMCallResult:
    return LLMCallResult(
        payload=payload,
        tokens_in=180,
        tokens_out=70,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost_usd=Decimal("0.003000"),
        latency_ms=190,
        provider="gemini",
        model="gemini-1.5-flash",
    )


async def test_summarize_category_happy_path(test_session) -> None:
    user, account, run = await _seed_run(test_session)
    await _seed_email_summary(
        test_session,
        account=account,
        run=run,
        subject="Board packet",
        label="must_read",
        body_md="Board packet is ready.\n\n**Key points**\n- Review is Friday",
    )
    prompt, prompt_version_id = await _registered_prompt(test_session)
    provider = _Provider(
        [
            _call_result(
                {
                    "narrative": "Must-read mail centers on Friday's board review.",
                    "groups": [
                        {
                            "label": "Board review",
                            "bullets": ["Review is Friday"],
                            "item_refs": ["E1"],
                        },
                    ],
                    "confidence": 0.91,
                },
            ),
        ],
    )
    repo = SummariesRepo(cipher=None)

    outcome = await summarize_category(
        CategoryDigestInputs(
            user_id=user.id,
            run_id=run.id,
            category="must_read",
            prompt=prompt,
            prompt_version_id=prompt_version_id,
            llm=LLMClient(primary=provider),
            repo=repo,
        ),
        session=test_session,
    )

    assert outcome.ok is True
    assert outcome.confidence == pytest.approx(0.91)
    assert provider.calls == 1
    assert '"ref":"E1"' in provider.prompts[0]

    row = (
        await test_session.execute(
            select(Summary).where(Summary.kind == "category_digest"),
        )
    ).scalar_one()
    assert row.run_id == run.id
    assert row.category == "must_read"
    assert repo.decrypt_category_narrative(row=row, user_id=user.id).startswith("Must-read")
    groups = repo.decrypt_category_groups(row=row, user_id=user.id)
    assert groups[0].label == "Board review"

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert len(calls) == 1
    assert calls[0].run_id == run.id
    assert calls[0].email_id is None


async def test_summarize_category_writes_deterministic_fallback_on_llm_failure(
    test_session,
) -> None:
    """Category digest failures degrade instead of failing the whole scan."""
    user, account, run = await _seed_run(test_session)
    await _seed_email_summary(
        test_session,
        account=account,
        run=run,
        subject="Planning notes",
        label="good_to_read",
        body_md="Planning notes landed.\n\n**Key points**\n- Review the launch date",
    )
    prompt, prompt_version_id = await _registered_prompt(test_session)
    provider = _Provider([LLMProviderError("malformed json", retryable=False)])
    repo = SummariesRepo(cipher=None)

    outcome = await summarize_category(
        CategoryDigestInputs(
            user_id=user.id,
            run_id=run.id,
            category="good_to_read",
            prompt=prompt,
            prompt_version_id=prompt_version_id,
            llm=LLMClient(primary=provider),
            repo=repo,
        ),
        session=test_session,
    )

    assert outcome.ok is True
    assert outcome.fallback_used is True
    assert outcome.confidence == pytest.approx(0.55)

    row = (
        await test_session.execute(
            select(Summary).where(Summary.kind == "category_digest"),
        )
    ).scalar_one()
    assert row.model == "deterministic-category-fallback"
    assert repo.decrypt_category_narrative(row=row, user_id=user.id).startswith("Good To Read")
    groups = repo.decrypt_category_groups(row=row, user_id=user.id)
    assert groups[0].label == "Planning notes"
    assert groups[0].item_refs == ("E1",)

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert len(calls) == 1
    assert calls[0].status == "error"
    assert calls[0].run_id == run.id


async def test_summarize_category_is_idempotent(test_session) -> None:
    user, account, run = await _seed_run(test_session)
    await _seed_email_summary(
        test_session,
        account=account,
        run=run,
        subject="Planning",
        label="good_to_read",
        body_md="Planning notes landed.",
    )
    prompt, prompt_version_id = await _registered_prompt(test_session)
    provider = _Provider(
        [
            _call_result(
                {
                    "narrative": "Planning notes landed.",
                    "groups": [],
                    "confidence": 0.9,
                },
            ),
            _call_result(
                {
                    "narrative": "Should not be used.",
                    "groups": [],
                    "confidence": 0.9,
                },
            ),
        ],
    )
    inputs = CategoryDigestInputs(
        user_id=user.id,
        run_id=run.id,
        category="good_to_read",
        prompt=prompt,
        prompt_version_id=prompt_version_id,
        llm=LLMClient(primary=provider),
        repo=SummariesRepo(cipher=None),
    )

    first = await summarize_category(inputs, session=test_session)
    second = await summarize_category(inputs, session=test_session)

    count = (
        await test_session.execute(
            select(func.count(Summary.id)).where(Summary.kind == "category_digest"),
        )
    ).scalar_one()
    assert first.ok is True
    assert second.ok is False
    assert second.skipped_reason == "already summarized"
    assert provider.calls == 1
    assert count == 1


async def test_summarize_category_rejects_partial_set(test_session) -> None:
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="Missing summary")
    test_session.add(email)
    await test_session.flush()
    test_session.add(DigestRunEmail(run_id=run.id, email_id=email.id))
    test_session.add(
        Classification(
            email_id=email.id,
            label="must_read",
            score=Decimal("0.9"),
            rubric_version=1,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
        ),
    )
    await test_session.flush()
    prompt, prompt_version_id = await _registered_prompt(test_session)
    provider = _Provider([])

    with pytest.raises(CategoryDigestNotReadyError):
        await summarize_category(
            CategoryDigestInputs(
                user_id=user.id,
                run_id=run.id,
                category="must_read",
                prompt=prompt,
                prompt_version_id=prompt_version_id,
                llm=LLMClient(primary=provider),
                repo=SummariesRepo(cipher=None),
            ),
            session=test_session,
        )

    assert provider.calls == 0


async def test_summarize_category_uses_successful_items_after_terminal_failure(
    test_session,
) -> None:
    """A terminal per-email failure does not block a best-effort category digest."""
    user, account, run = await _seed_run(test_session)
    await _seed_email_summary(
        test_session,
        account=account,
        run=run,
        subject="Available summary",
        label="must_read",
        body_md="Available summary content.",
    )
    failed_email = _email(account=account, subject="Failed summary")
    summary_prompt = PromptVersion(
        name="summarize_relevant",
        version=1,
        content="summarize",
        content_hash=hashlib.sha256(b"failed-summary").digest(),
        model="gemini-1.5-flash",
        params={},
    )
    test_session.add_all([failed_email, summary_prompt])
    await test_session.flush()
    test_session.add_all(
        [
            DigestRunEmail(run_id=run.id, email_id=failed_email.id),
            Classification(
                email_id=failed_email.id,
                label="must_read",
                score=Decimal("0.9"),
                rubric_version=1,
                decision_source="model",
                model="gemini-1.5-flash",
                tokens_in=10,
                tokens_out=5,
            ),
            PromptCallLog(
                prompt_version_id=summary_prompt.id,
                email_id=failed_email.id,
                model="gemini-1.5-flash",
                tokens_in=0,
                tokens_out=0,
                cost_usd=Decimal("0"),
                latency_ms=0,
                status="error",
                provider="openrouter:gemini-flash",
                run_id=run.id,
            ),
        ],
    )
    await test_session.flush()
    prompt, prompt_version_id = await _registered_prompt(test_session)
    provider = _Provider(
        [
            _call_result(
                {
                    "narrative": "Available must-read summary.",
                    "groups": [],
                    "confidence": 0.8,
                },
            ),
        ],
    )

    outcome = await summarize_category(
        CategoryDigestInputs(
            user_id=user.id,
            run_id=run.id,
            category="must_read",
            prompt=prompt,
            prompt_version_id=prompt_version_id,
            llm=LLMClient(primary=provider),
            repo=SummariesRepo(cipher=None),
        ),
        session=test_session,
    )

    assert outcome.ok is True
    assert provider.calls == 1
    assert "Available summary" in provider.prompts[0]
    assert "Failed summary" not in provider.prompts[0]


async def test_upsert_category_digest_round_trip_and_replaces(test_session) -> None:
    user, _account, run = await _seed_run(test_session)
    repo = SummariesRepo(cipher=None)

    await repo.upsert_category_digest(
        test_session,
        SummaryCategoryDigestWrite(
            run_id=run.id,
            category="must_read",
            user_id=user.id,
            prompt_version_id=None,
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            narrative="First",
            groups=(CategoryDigestGroup(label="One", bullets=("A",), item_refs=("E1",)),),
            confidence=Decimal("0.800"),
            cache_hit=False,
        ),
    )
    row = await repo.upsert_category_digest(
        test_session,
        SummaryCategoryDigestWrite(
            run_id=run.id,
            category="must_read",
            user_id=user.id,
            prompt_version_id=None,
            model="gemini-1.5-flash",
            tokens_in=11,
            tokens_out=6,
            narrative="Second",
            groups=(CategoryDigestGroup(label="Two", bullets=("B",), item_refs=("E2",)),),
            confidence=Decimal("0.900"),
            cache_hit=True,
        ),
    )

    rows = (
        (
            await test_session.execute(
                select(Summary).where(Summary.kind == "category_digest"),
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert repo.decrypt_category_narrative(row=row, user_id=user.id) == "Second"
    assert repo.decrypt_category_groups(row=row, user_id=user.id)[0].label == "Two"


async def test_upsert_category_digest_fake_kms_round_trip(test_session) -> None:
    user, _account, run = await _seed_run(test_session)
    repo = SummariesRepo(cipher=EnvelopeCipher(key_id="alias/test", client=_FakeKms()))

    row = await repo.upsert_category_digest(
        test_session,
        SummaryCategoryDigestWrite(
            run_id=run.id,
            category="good_to_read",
            user_id=user.id,
            prompt_version_id=None,
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            narrative="Encrypted narrative",
            groups=(CategoryDigestGroup(label="FYI", bullets=("A",), item_refs=("E1",)),),
            confidence=Decimal("0.800"),
            cache_hit=False,
        ),
    )

    assert row.body_md_ct != b"Encrypted narrative"
    assert repo.decrypt_category_narrative(row=row, user_id=user.id) == "Encrypted narrative"
    assert repo.decrypt_category_groups(row=row, user_id=user.id)[0].item_refs == ("E1",)


async def _seed_run(test_session) -> tuple[User, ConnectedAccount, DigestRun]:
    user = User(email=f"user-{uuid.uuid4()}@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        provider="gmail",
        email="mailbox@example.com",
        status="active",
    )
    test_session.add(account)
    await test_session.flush()
    run = DigestRun(
        user_id=user.id,
        status="running",
        trigger_type="manual",
        started_at=datetime.now(tz=UTC),
        stats={"account_ids": [str(account.id)]},
        cost_cents=0,
    )
    test_session.add(run)
    await test_session.flush()
    return user, account, run


async def _seed_email_summary(
    test_session,
    *,
    account: ConnectedAccount,
    run: DigestRun,
    subject: str,
    label: str,
    body_md: str,
) -> Email:
    email = _email(account=account, subject=subject)
    test_session.add(email)
    await test_session.flush()
    test_session.add(DigestRunEmail(run_id=run.id, email_id=email.id))
    test_session.add(
        Classification(
            email_id=email.id,
            label=label,
            score=Decimal("0.9"),
            rubric_version=1,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
        ),
    )
    test_session.add(
        Summary(
            kind="email",
            email_id=email.id,
            cluster_id=None,
            prompt_version_id=None,
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            body_md_ct=body_md.encode("utf-8"),
            entities_ct=None,
            cache_hit=False,
            confidence=Decimal("0.900"),
        ),
    )
    await test_session.flush()
    return email


def _email(*, account: ConnectedAccount, subject: str) -> Email:
    digest = hashlib.sha256(f"{account.id}:{subject}".encode()).digest()
    return Email(
        account_id=account.id,
        gmail_message_id=str(uuid.uuid4()),
        thread_id=str(uuid.uuid4()),
        internal_date=datetime.now(tz=UTC),
        from_addr="sender@example.com",
        to_addrs=[account.email],
        cc_addrs=[],
        subject=subject,
        snippet=subject,
        labels=["UNREAD"],
        content_hash=digest,
        size_bytes=42,
    )


async def _registered_prompt(test_session) -> tuple[RegisteredPrompt, uuid.UUID]:
    content = "digest {{run_id}} {{category}} {{items_json}}"
    pv = PromptVersion(
        name="category_digest",
        version=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).digest(),
        model="gemini-1.5-flash",
        params={"temperature": 0.1, "max_tokens": 700},
    )
    test_session.add(pv)
    await test_session.flush()
    spec = PromptSpec(
        name="category_digest",
        version=1,
        content=content,
        model="gemini-1.5-flash",
        temperature=0.1,
        max_tokens=700,
    )
    return (
        RegisteredPrompt(
            spec=spec,
            content_hash=pv.content_hash,
            frontmatter={"id": "category_digest"},
            source_path=None,
        ),
        pv.id,
    )
