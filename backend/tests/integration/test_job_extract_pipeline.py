"""End-to-end job-extraction pipeline test (plan §14 Phase 4).

Covers:

* happy path → ``job_matches`` row written with encrypted
  ``match_reason``; predicate evaluation + salary corroboration both
  succeed; ``passed_filter=True`` is persisted.
* hallucinated salary → row is still written but with comp fields
  zeroed out and ``passed_filter=False``.
* predicate fails → row is persisted with ``passed_filter=False`` so
  the UI can surface the posting with a "does not match your filters"
  badge.
* LLM failure → no row written; error-status call log lands.
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
    JobFilter,
    JobMatch,
    PromptCallLog,
    PromptVersion,
    User,
)
from app.llm.client import LLMClient
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec
from app.services.jobs import (
    ExtractInputs,
    JobMatchesRepo,
    extract_job,
)
from app.services.prompts.registry import RegisteredPrompt


class _FakeKms:
    def __init__(self) -> None:
        self._master = b"J" * 32

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
    tokens_in: int = 180,
    tokens_out: int = 90,
    cache_read: int = 0,
) -> LLMCallResult:
    return LLMCallResult(
        payload=payload,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_cache_read=cache_read,
        tokens_cache_write=0,
        cost_usd=Decimal("0.003000"),
        latency_ms=220,
        provider=provider,
        model="gemini-1.5-flash",
    )


async def _seed_job_candidate(
    session,
    user: User,
    *,
    excerpt: str,
) -> tuple[ConnectedAccount, Email]:
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
        gmail_message_id="m-job-1",
        thread_id="t-1",
        internal_date=datetime.now(tz=UTC),
        from_addr="recruiter@acme.example",
        to_addrs=[],
        cc_addrs=[],
        subject="Staff Backend Engineer @ Acme",
        snippet="Short snippet.",
        labels=[],
        content_hash=hashlib.sha256(b"job").digest(),
    )
    session.add(email)
    await session.flush()
    email.body = EmailContentBlob(
        message_id=email.id,
        storage_backend="pg",
        plain_text_excerpt=excerpt,
    )
    session.add(
        Classification(
            email_id=email.id,
            label="job_candidate",
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
    return entry, pv.id


@pytest.mark.asyncio
async def test_extract_happy_path_passes_filter(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    excerpt = (
        "Hi — we're hiring a Staff Backend Engineer at Acme. Fully remote in "
        "the US. Comp is $210,000-$260,000 plus equity. Apply at "
        "https://acme.example/jobs/staff-backend"
    )
    _account, email = await _seed_job_candidate(test_session, user, excerpt=excerpt)
    test_session.add(
        JobFilter(
            user_id=user.id,
            name="remote-staff-roles",
            predicate={
                "min_comp": 180_000,
                "currency": "USD",
                "remote_required": True,
                "seniority_in": ["senior", "staff", "principal"],
                "min_confidence": 0.7,
            },
            version=2,
            active=True,
        ),
    )
    await test_session.flush()
    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_FakeProvider(
            "gemini",
            [
                _call_result(
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
                        "source_url": "https://acme.example/jobs/staff-backend",
                        "match_reason": "Remote staff-level backend role; fits preferences.",
                        "confidence": 0.92,
                    },
                ),
            ],
        ),
    )
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    repo = JobMatchesRepo(cipher=cipher)

    outcome = await extract_job(
        ExtractInputs(
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
    assert outcome.passed_filter is True
    assert outcome.corroborated is True
    assert outcome.match_score == pytest.approx(0.92)

    row = (
        await test_session.execute(select(JobMatch).where(JobMatch.email_id == email.id))
    ).scalar_one()
    assert row.passed_filter is True
    assert row.filter_version == 2
    assert row.title == "Staff Backend Engineer"
    assert row.comp_min == 210_000
    assert row.comp_max == 260_000
    assert row.currency == "USD"
    # Ciphertext is not plaintext.
    assert bytes(row.match_reason_ct) != b"Remote staff-level backend role; fits preferences."
    assert repo.decrypt_reason(row=row, user_id=user.id).startswith("Remote staff-level")

    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert len(calls) == 1
    assert calls[0].status == "ok"


@pytest.mark.asyncio
async def test_extract_job_skips_existing_match(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    _account, email = await _seed_job_candidate(test_session, user, excerpt="body")
    registered, prompt_version_id = await _registered_prompt(test_session)
    test_session.add(
        JobMatch(
            email_id=email.id,
            title="Existing",
            company="Acme",
            match_score=Decimal("0.8"),
            match_reason_ct=b"\x00",
            passed_filter=False,
            filter_version=0,
        ),
    )
    await test_session.flush()

    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    outcome = await extract_job(
        ExtractInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            prompt_version_id=prompt_version_id,
            llm=LLMClient(primary=_FakeProvider("gemini", [])),
            repo=JobMatchesRepo(cipher=cipher),
        ),
        session=test_session,
    )

    assert outcome.ok is False
    assert outcome.skipped_reason == "already extracted"


@pytest.mark.asyncio
async def test_extract_rejects_hallucinated_salary(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    # Body mentions only $150k but model fabricates $250k-$300k.
    excerpt = "Staff role at Beta. Base salary $150,000. Apply soon."
    _account, email = await _seed_job_candidate(test_session, user, excerpt=excerpt)
    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_FakeProvider(
            "gemini",
            [
                _call_result(
                    {
                        "title": "Staff Platform Engineer",
                        "company": "Beta",
                        "location": "Remote",
                        "remote": True,
                        "comp_min": 250_000,
                        "comp_max": 300_000,
                        "currency": "USD",
                        "comp_phrase": "$250k-$300k",
                        "seniority": "staff",
                        "source_url": None,
                        "match_reason": "fits budget",
                        "confidence": 0.9,
                    },
                ),
            ],
        ),
    )
    repo = JobMatchesRepo(cipher=None)

    outcome = await extract_job(
        ExtractInputs(
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
    assert outcome.corroborated is False
    assert outcome.passed_filter is False  # confidence knocked below floor
    assert outcome.match_score < 0.7

    row = (
        await test_session.execute(select(JobMatch).where(JobMatch.email_id == email.id))
    ).scalar_one()
    assert row.comp_min is None
    assert row.comp_max is None
    assert row.currency is None
    assert row.comp_phrase is None
    assert row.passed_filter is False


@pytest.mark.asyncio
async def test_extract_honors_filter_rejection(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    excerpt = (
        "Senior Backend Engineer at Gamma. On-site only, Bangalore. "
        "Comp ₹40,00,000. Apply at https://gamma.example/careers"
    )
    _account, email = await _seed_job_candidate(test_session, user, excerpt=excerpt)
    # Filter requires remote + USD; posting is INR + on-site → rejected.
    test_session.add(
        JobFilter(
            user_id=user.id,
            name="remote-usd-only",
            predicate={"remote_required": True, "currency": "USD"},
            version=1,
            active=True,
        ),
    )
    await test_session.flush()
    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_FakeProvider(
            "gemini",
            [
                _call_result(
                    {
                        "title": "Senior Backend Engineer",
                        "company": "Gamma",
                        "location": "Bangalore",
                        "remote": False,
                        "comp_min": None,
                        "comp_max": None,
                        "currency": None,
                        "comp_phrase": None,
                        "seniority": "senior",
                        "source_url": "https://gamma.example/careers",
                        "match_reason": "On-site senior role; location mismatch.",
                        "confidence": 0.82,
                    },
                ),
            ],
        ),
    )
    repo = JobMatchesRepo(cipher=None)

    outcome = await extract_job(
        ExtractInputs(
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
    assert outcome.passed_filter is False
    assert outcome.match_score == pytest.approx(0.82)

    row = (
        await test_session.execute(select(JobMatch).where(JobMatch.email_id == email.id))
    ).scalar_one()
    assert row.passed_filter is False
    assert row.filter_version == 1  # snapshot preserved even on rejection
    assert row.title == "Senior Backend Engineer"


@pytest.mark.asyncio
async def test_extract_without_filters_confidence_gate_still_applies(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    excerpt = "Generic recruiter reach-out. Would love to chat."
    _account, email = await _seed_job_candidate(test_session, user, excerpt=excerpt)
    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_FakeProvider(
            "gemini",
            [
                _call_result(
                    {
                        "title": "unspecified engineering role",
                        "company": "Headhunter",
                        "location": None,
                        "remote": None,
                        "comp_min": None,
                        "comp_max": None,
                        "currency": None,
                        "comp_phrase": None,
                        "seniority": None,
                        "source_url": None,
                        "match_reason": "Generic recruiter reach-out.",
                        "confidence": 0.35,
                    },
                ),
            ],
        ),
    )
    repo = JobMatchesRepo(cipher=None)

    outcome = await extract_job(
        ExtractInputs(
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
    # No filters configured but confidence is below the floor.
    assert outcome.passed_filter is False

    row = (
        await test_session.execute(select(JobMatch).where(JobMatch.email_id == email.id))
    ).scalar_one()
    assert row.passed_filter is False
    assert row.filter_version == 0


@pytest.mark.asyncio
async def test_extract_handles_llm_exhaustion(test_session) -> None:
    user = User(email="me@example.com", tz="UTC", status="active")
    test_session.add(user)
    await test_session.flush()
    excerpt = "Staff role details."
    _account, email = await _seed_job_candidate(test_session, user, excerpt=excerpt)
    registered, prompt_version_id = await _registered_prompt(test_session)

    llm = LLMClient(
        primary=_FakeProvider(
            "gemini",
            [LLMProviderError("empty", retryable=False)],
        ),
    )
    repo = JobMatchesRepo(cipher=None)

    outcome = await extract_job(
        ExtractInputs(
            email_id=email.id,
            user_id=user.id,
            prompt=registered,
            prompt_version_id=prompt_version_id,
            llm=llm,
            repo=repo,
        ),
        session=test_session,
    )
    assert outcome.ok is False
    assert outcome.skipped_reason

    rows = (await test_session.execute(select(JobMatch))).scalars().all()
    assert rows == []
    calls = (await test_session.execute(select(PromptCallLog))).scalars().all()
    assert calls and calls[0].status == "error"
