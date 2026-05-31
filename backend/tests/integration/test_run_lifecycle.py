"""Integration tests for digest-run lifecycle finalization."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Classification,
    ConnectedAccount,
    DigestRun,
    Email,
    PromptCallLog,
    PromptVersion,
    Summary,
    User,
)
from app.services.runs import maybe_finalize_run


async def test_maybe_finalize_run_completes_and_clears_lock(
    test_session: AsyncSession,
) -> None:
    """A run completes when no classification, summary, or job work remains."""
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="FYI")
    test_session.add(email)
    await test_session.flush()
    test_session.add(
        Classification(
            email_id=email.id,
            label="ignore",
            score=Decimal("0.900"),
            rubric_version=1,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            is_newsletter=False,
            is_job_candidate=False,
        ),
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is True
    assert run.status == "complete"
    assert run.completed_at is not None
    assert run.stats["ingested"] == 1
    assert run.stats["classified"] == 1
    assert run.stats["summarized"] == 0
    assert user.current_run_id is None
    assert user.current_run_started_at is None
    assert user.last_run_finished_at is not None


async def test_maybe_finalize_run_waits_for_pending_summary(
    test_session: AsyncSession,
) -> None:
    """A must-read email without a summary keeps the run running."""
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="Board package")
    test_session.add(email)
    await test_session.flush()
    test_session.add(
        Classification(
            email_id=email.id,
            label="must_read",
            score=Decimal("0.950"),
            rubric_version=1,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            is_newsletter=False,
            is_job_candidate=False,
        ),
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is False
    assert run.status == "running"
    assert run.completed_at is None
    assert user.current_run_id == str(run.id)


async def test_maybe_finalize_run_fails_on_prompt_error(
    test_session: AsyncSession,
) -> None:
    """Provider failures mark the run failed and release the user lock."""
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="Needs model")
    prompt = PromptVersion(
        name="triage",
        version=1,
        content="triage",
        content_hash=hashlib.sha256(b"triage").digest(),
        model="gemini-1.5-flash",
        params={},
    )
    test_session.add_all([email, prompt])
    await test_session.flush()
    test_session.add(
        Classification(
            email_id=email.id,
            label="needs_review",
            score=Decimal("0.000"),
            rubric_version=1,
            prompt_version_id=prompt.id,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=0,
            tokens_out=0,
            is_newsletter=False,
            is_job_candidate=False,
        ),
    )
    test_session.add(
        PromptCallLog(
            prompt_version_id=prompt.id,
            email_id=email.id,
            model="gemini-1.5-flash",
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0.000000"),
            latency_ms=0,
            status="error",
            provider="openrouter:gemini-flash",
            run_id=run.id,
        ),
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is True
    assert run.status == "failed"
    assert run.error == "One or more LLM provider calls failed during the scan."
    assert user.current_run_id is None
    assert user.last_run_finished_at is None


async def test_maybe_finalize_run_completes_on_job_extract_error(
    test_session: AsyncSession,
) -> None:
    """A failed optional job extraction does not fail the digest run."""
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="Recruiter intro")
    prompt = PromptVersion(
        name="job_extract",
        version=1,
        content="job",
        content_hash=hashlib.sha256(b"job").digest(),
        model="gemini-1.5-flash",
        params={},
    )
    test_session.add_all([email, prompt])
    await test_session.flush()
    test_session.add(
        Classification(
            email_id=email.id,
            label="ignore",
            score=Decimal("0.850"),
            rubric_version=1,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            is_newsletter=False,
            is_job_candidate=True,
        ),
    )
    test_session.add(
        PromptCallLog(
            prompt_version_id=prompt.id,
            email_id=email.id,
            model="gemini-1.5-flash",
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0.000000"),
            latency_ms=0,
            status="error",
            provider="openrouter:gemini-flash",
            run_id=run.id,
        ),
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is True
    assert run.status == "complete"
    assert run.error is None
    assert run.stats["classified"] == 1
    assert user.current_run_id is None
    assert user.last_run_finished_at is not None


async def test_maybe_finalize_run_completes_after_summary_lands(
    test_session: AsyncSession,
) -> None:
    """A summarizable email completes after its summary row exists."""
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="Planning")
    prompt = PromptVersion(
        name="summarize_relevant",
        version=1,
        content="summarize",
        content_hash=hashlib.sha256(b"summarize").digest(),
        model="gemini-1.5-flash",
        params={},
    )
    test_session.add_all([email, prompt])
    await test_session.flush()
    test_session.add(
        Classification(
            email_id=email.id,
            label="must_read",
            score=Decimal("0.950"),
            rubric_version=1,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            is_newsletter=False,
            is_job_candidate=False,
        ),
    )
    await test_session.flush()
    test_session.add(
        Summary(
            kind="email",
            email_id=email.id,
            cluster_id=None,
            prompt_version_id=prompt.id,
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=8,
            body_md_ct=b"summary",
            entities_ct=None,
            cache_hit=False,
            confidence=Decimal("0.900"),
        ),
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is True
    assert run.status == "complete"
    assert run.stats["summarized"] == 1
    assert run.stats["new_must_read"] == 1


async def _seed_run(
    session: AsyncSession,
) -> tuple[User, ConnectedAccount, DigestRun]:
    """Insert a user, active account, and running manual digest run."""
    now = datetime.now(tz=UTC)
    run_id = uuid.uuid4()
    user = User(
        email=f"user-{run_id}@example.com",
        current_run_id=str(run_id),
        current_run_started_at=now,
    )
    session.add(user)
    await session.flush()
    account = ConnectedAccount(
        user_id=user.id,
        email=f"mailbox-{run_id}@example.com",
        gmail_account_id=str(run_id),
    )
    session.add(account)
    await session.flush()
    run = DigestRun(
        id=run_id,
        user_id=user.id,
        status="queued",
        trigger_type="manual",
        started_at=now,
        completed_at=None,
        stats={
            "ingested": 0,
            "classified": 0,
            "summarized": 0,
            "new_must_read": 0,
            "account_ids": [str(account.id)],
        },
        cost_cents=0,
    )
    session.add(run)
    await session.flush()
    return user, account, run


def _email(*, account: ConnectedAccount, subject: str) -> Email:
    """Build a minimal email row for run-lifecycle tests."""
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
        labels=[],
        content_hash=digest,
        size_bytes=42,
    )
