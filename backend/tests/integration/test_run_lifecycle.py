"""Integration tests for digest-run lifecycle finalization."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import (
    Base,
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
from app.services.runs import (
    mark_unsubscribe_hygiene_enqueued,
    maybe_finalize_run,
    stamp_run_membership,
)
from app.workers.messages import CategoryDigestMessage, TechNewsClusterMessage


@pytest_asyncio.fixture()
async def file_sessionmaker(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker over file-backed SQLite so each session is its own connection.

    Mirrors prod's ``expire_on_commit=False`` so a session keeps a stale
    ``DigestRun`` after another session commits, like concurrent workers.
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}",
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


async def test_maybe_finalize_run_completes_and_clears_lock(
    test_session: AsyncSession,
) -> None:
    """A run completes when no classification or summary work remains."""
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="FYI")
    test_session.add(email)
    await test_session.flush()
    await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(email.id,))
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
    await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(email.id,))
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
        name="summarize_relevant",
        version=1,
        content="summarize",
        content_hash=hashlib.sha256(b"summarize").digest(),
        model="gemini-1.5-flash",
        params={},
    )
    test_session.add_all([email, prompt])
    await test_session.flush()
    await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(email.id,))
    test_session.add(
        Classification(
            email_id=email.id,
            label="must_read",
            score=Decimal("0.000"),
            rubric_version=1,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=0,
            tokens_out=0,
            is_newsletter=False,
            needs_review=True,
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

    sent: list[CategoryDigestMessage] = []
    terminal = await maybe_finalize_run(
        session=test_session,
        user_id=user.id,
        run_id=run.id,
        category_digest_sender=sent.append,
    )

    assert terminal is True
    assert run.status == "failed"
    assert run.error == "One or more LLM provider calls failed during the scan."
    assert sent == []
    assert user.current_run_id is None
    assert user.last_run_finished_at is None


async def test_maybe_finalize_run_waits_for_other_work_after_prompt_error(
    test_session: AsyncSession,
) -> None:
    """A prompt error does not freeze run counters while other work is pending."""
    user, account, run = await _seed_run(test_session)
    failed_email = _email(account=account, subject="Provider exhausted")
    pending_email = _email(account=account, subject="Still processing")
    prompt = PromptVersion(
        name="triage",
        version=1,
        content="triage",
        content_hash=hashlib.sha256(b"triage-pending").digest(),
        model="gemini-1.5-flash",
        params={},
    )
    test_session.add_all([failed_email, pending_email, prompt])
    await test_session.flush()
    await stamp_run_membership(
        session=test_session,
        run_id=run.id,
        email_ids=(failed_email.id, pending_email.id),
    )
    test_session.add_all(
        [
            Classification(
                email_id=failed_email.id,
                label="ignore",
                score=Decimal("0.000"),
                rubric_version=0,
                decision_source="model",
                model="",
                tokens_in=0,
                tokens_out=0,
                is_newsletter=False,
                needs_review=True,
            ),
            PromptCallLog(
                prompt_version_id=prompt.id,
                email_id=failed_email.id,
                model="gemini-1.5-flash",
                tokens_in=0,
                tokens_out=0,
                cost_usd=Decimal("0.000000"),
                latency_ms=0,
                status="error",
                provider="openrouter:gemini-flash",
                run_id=run.id,
            ),
        ],
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is False
    assert run.status == "running"
    assert run.stats["classified"] == 1

    test_session.add_all(
        [
            Classification(
                email_id=pending_email.id,
                label="ignore",
                score=Decimal("0.900"),
                rubric_version=1,
                decision_source="model",
                model="gemini-1.5-flash",
                tokens_in=10,
                tokens_out=5,
                is_newsletter=False,
            ),
            PromptCallLog(
                prompt_version_id=prompt.id,
                email_id=pending_email.id,
                model="gemini-1.5-flash",
                tokens_in=10,
                tokens_out=5,
                cost_usd=Decimal("0.020000"),
                latency_ms=10,
                status="ok",
                provider="openrouter:gemini-flash",
                run_id=run.id,
            ),
        ],
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is True
    assert run.status == "failed"
    assert run.stats["ingested"] == 2
    assert run.stats["classified"] == 2
    assert run.cost_cents == 2


async def test_maybe_finalize_run_treats_failed_cluster_as_terminal(
    test_session: AsyncSession,
) -> None:
    """A terminal newsletter-cluster failure does not strand the run."""
    user, account, run = await _seed_run(test_session)
    emails = (
        _email(account=account, subject="Newsletter one"),
        _email(account=account, subject="Newsletter two"),
    )
    prompt = PromptVersion(
        name="newsletter_group",
        version=1,
        content="cluster",
        content_hash=hashlib.sha256(b"newsletter-cluster").digest(),
        model="gemini-1.5-flash",
        params={},
    )
    test_session.add_all([*emails, prompt])
    await test_session.flush()
    await stamp_run_membership(
        session=test_session,
        run_id=run.id,
        email_ids=(email.id for email in emails),
    )
    for email in emails:
        test_session.add_all(
            [
                Classification(
                    email_id=email.id,
                    label="ignore",
                    score=Decimal("0.800"),
                    rubric_version=1,
                    decision_source="model",
                    model="gemini-1.5-flash",
                    tokens_in=10,
                    tokens_out=5,
                    is_newsletter=True,
                ),
                Summary(
                    kind="email",
                    email_id=email.id,
                    cluster_id=None,
                    prompt_version_id=None,
                    model="gemini-1.5-flash",
                    tokens_in=10,
                    tokens_out=5,
                    body_md_ct=b"summary",
                    entities_ct=None,
                    cache_hit=False,
                    confidence=Decimal("0.900"),
                ),
            ],
        )
    test_session.add(
        PromptCallLog(
            prompt_version_id=prompt.id,
            email_id=None,
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
    assert run.stats["ingested"] == 2
    assert run.stats["classified"] == 2
    assert run.stats["summarized"] == 2


async def test_maybe_finalize_run_ignores_recovered_category_digest_error(
    test_session: AsyncSession,
) -> None:
    """Category digest prompt errors are non-fatal once a digest row exists."""
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="Planning")
    prompt = PromptVersion(
        name="category_digest",
        version=1,
        content="category",
        content_hash=hashlib.sha256(b"category").digest(),
        model="gemini-1.5-flash",
        params={},
    )
    test_session.add_all([email, prompt])
    await test_session.flush()
    await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(email.id,))
    test_session.add_all(
        [
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
            ),
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
            Summary(
                kind="category_digest",
                email_id=None,
                cluster_id=None,
                run_id=run.id,
                category="must_read",
                prompt_version_id=prompt.id,
                model="deterministic-category-fallback",
                tokens_in=0,
                tokens_out=0,
                body_md_ct=b"digest",
                entities_ct=None,
                cache_hit=False,
                confidence=Decimal("0.550"),
            ),
            PromptCallLog(
                prompt_version_id=prompt.id,
                email_id=None,
                model="gemini-1.5-flash",
                tokens_in=0,
                tokens_out=0,
                cost_usd=Decimal("0.000000"),
                latency_ms=0,
                status="error",
                provider="openrouter:gemini-flash",
                run_id=run.id,
            ),
        ],
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is True
    assert run.status == "complete"
    assert run.error is None
    assert user.current_run_id is None


async def test_mark_unsubscribe_hygiene_enqueued_is_per_account_run(
    test_session: AsyncSession,
) -> None:
    """Unsubscribe hygiene dispatch is debounced per account/run."""
    user, account, run = await _seed_run(test_session)
    second_account = ConnectedAccount(
        user_id=user.id,
        email=f"second-{run.id}@example.com",
        gmail_account_id=f"second-{run.id}",
    )
    test_session.add(second_account)
    await test_session.flush()

    first = await mark_unsubscribe_hygiene_enqueued(
        session=test_session,
        run_id=run.id,
        account_id=account.id,
    )
    repeat = await mark_unsubscribe_hygiene_enqueued(
        session=test_session,
        run_id=run.id,
        account_id=account.id,
    )
    second = await mark_unsubscribe_hygiene_enqueued(
        session=test_session,
        run_id=run.id,
        account_id=second_account.id,
    )

    assert first is True
    assert repeat is False
    assert second is True
    assert run.stats["unsubscribe_hygiene_enqueued"] == sorted(
        [str(account.id), str(second_account.id)],
    )


async def test_maybe_finalize_run_completes_after_summary_lands(
    test_session: AsyncSession,
) -> None:
    """A summarizable email completes only after its category digest exists."""
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
    await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(email.id,))
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

    sent: list[CategoryDigestMessage] = []
    terminal = await maybe_finalize_run(
        session=test_session,
        user_id=user.id,
        run_id=run.id,
        category_digest_sender=sent.append,
    )

    assert terminal is False
    assert run.status == "running"
    assert len(sent) == 1
    assert sent[0].run_id == run.id
    assert sent[0].category == "must_read"

    repeated = await maybe_finalize_run(
        session=test_session,
        user_id=user.id,
        run_id=run.id,
        category_digest_sender=sent.append,
    )
    assert repeated is False
    assert len(sent) == 1

    test_session.add(
        Summary(
            kind="category_digest",
            email_id=None,
            cluster_id=None,
            run_id=run.id,
            category="must_read",
            prompt_version_id=prompt.id,
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=8,
            body_md_ct=b"digest",
            entities_ct=None,
            cache_hit=False,
            confidence=Decimal("0.900"),
        ),
    )
    await test_session.flush()

    completed = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert completed is True
    assert run.status == "complete"
    assert run.stats["summarized"] == 1
    assert run.stats["new_must_read"] == 1


async def test_category_digest_trigger_waits_for_classify_and_email_summary(
    test_session: AsyncSession,
) -> None:
    """Category digest messages are emitted only after prerequisite work drains."""
    user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="Board package")
    test_session.add(email)
    await test_session.flush()
    await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(email.id,))
    sent: list[CategoryDigestMessage] = []

    await maybe_finalize_run(
        session=test_session,
        user_id=user.id,
        run_id=run.id,
        category_digest_sender=sent.append,
    )
    assert sent == []

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
        ),
    )
    await test_session.flush()

    await maybe_finalize_run(
        session=test_session,
        user_id=user.id,
        run_id=run.id,
        category_digest_sender=sent.append,
    )
    assert sent == []

    test_session.add(
        Summary(
            kind="email",
            email_id=email.id,
            cluster_id=None,
            prompt_version_id=None,
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

    await maybe_finalize_run(
        session=test_session,
        user_id=user.id,
        run_id=run.id,
        category_digest_sender=sent.append,
    )
    assert [message.category for message in sent] == ["must_read"]


async def test_maybe_finalize_run_ignores_non_member_pre_run_email(
    test_session: AsyncSession,
) -> None:
    """Old account leftovers do not block a new run's completion."""
    user, account, run = await _seed_run(test_session)
    member = _email(account=account, subject="Member")
    non_member = _email(account=account, subject="Old unclassified")
    test_session.add_all([member, non_member])
    await test_session.flush()
    await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(member.id,))
    test_session.add(
        Classification(
            email_id=member.id,
            label="ignore",
            score=Decimal("0.900"),
            rubric_version=1,
            decision_source="model",
            model="gemini-1.5-flash",
            tokens_in=10,
            tokens_out=5,
            is_newsletter=False,
        ),
    )
    await test_session.flush()

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is True
    assert run.status == "complete"
    assert run.stats["ingested"] == 1
    assert run.stats["classified"] == 1


async def test_maybe_finalize_run_completes_zero_new_email_run(
    test_session: AsyncSession,
) -> None:
    """A run with no member emails completes instead of hanging."""
    user, _account, run = await _seed_run(test_session)

    terminal = await maybe_finalize_run(session=test_session, user_id=user.id, run_id=run.id)

    assert terminal is True
    assert run.status == "complete"
    assert run.stats["ingested"] == 0
    assert user.current_run_id is None


async def test_stamp_run_membership_is_idempotent(test_session: AsyncSession) -> None:
    """Repeated stamps for the same run/email pair insert one edge."""
    _user, account, run = await _seed_run(test_session)
    email = _email(account=account, subject="Idempotent")
    test_session.add(email)
    await test_session.flush()

    first = await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(email.id,))
    second = await stamp_run_membership(session=test_session, run_id=run.id, email_ids=(email.id,))
    rows = (
        (
            await test_session.execute(
                select(DigestRunEmail).where(DigestRunEmail.run_id == run.id),
            )
        )
        .scalars()
        .all()
    )

    assert first == 1
    assert second == 0
    assert len(rows) == 1


async def test_tech_news_cluster_dispatch_waits_for_classification_and_covers_run(
    test_session: AsyncSession,
) -> None:
    """One cluster message per run, sent after the last classification lands.

    Regression: prod enqueued one partial cluster job per classified
    newsletter (12-23 per run).
    """
    user, account, run = await _seed_run(test_session)
    newsletters = [_email(account=account, subject=f"Newsletter {idx}") for idx in range(3)]
    not_newsletter = _email(account=account, subject="Board package")
    outside_run = _email(account=account, subject="Older newsletter")
    test_session.add_all([*newsletters, not_newsletter, outside_run])
    await test_session.flush()
    await stamp_run_membership(
        session=test_session,
        run_id=run.id,
        email_ids=(*(email.id for email in newsletters), not_newsletter.id),
    )
    test_session.add_all(
        [
            _classification(newsletters[0], is_newsletter=True),
            _classification(newsletters[1], is_newsletter=True),
            _classification(not_newsletter, is_newsletter=False),
            _classification(outside_run, is_newsletter=True),
        ],
    )
    await test_session.flush()
    sent: list[TechNewsClusterMessage] = []

    await maybe_finalize_run(
        session=test_session,
        user_id=user.id,
        run_id=run.id,
        tech_news_cluster_sender=sent.append,
    )
    assert sent == []

    test_session.add(_classification(newsletters[2], is_newsletter=True))
    await test_session.flush()
    for _ in range(3):  # every later worker record re-runs finalize
        terminal = await maybe_finalize_run(
            session=test_session,
            user_id=user.id,
            run_id=run.id,
            tech_news_cluster_sender=sent.append,
        )
        assert terminal is False

    assert len(sent) == 1
    assert sent[0].user_id == user.id
    assert sent[0].run_id == run.id
    assert set(sent[0].email_ids) == {email.id for email in newsletters}
    assert run.status == "running"
    assert await _cluster_claimed_at(test_session, run.id) is not None


async def test_tech_news_cluster_claim_survives_stale_concurrent_finalize(
    file_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A worker holding a stale ``DigestRun`` neither re-sends nor clears the claim.

    Finalizers rewrite ``stats`` from stale copies; the dedicated column
    must survive that.
    """
    async with file_sessionmaker() as session:
        user, run_id = await _seed_newsletter_run(session)
        await session.commit()
    sent: list[TechNewsClusterMessage] = []

    async with file_sessionmaker() as stale, file_sessionmaker() as winner:
        stale_run = await stale.get(DigestRun, run_id)
        assert stale_run is not None

        await maybe_finalize_run(
            session=winner,
            user_id=user,
            run_id=run_id,
            tech_news_cluster_sender=sent.append,
        )
        await winner.commit()

        await maybe_finalize_run(
            session=stale,
            user_id=user,
            run_id=run_id,
            tech_news_cluster_sender=sent.append,
        )
        await stale.commit()

    async with file_sessionmaker() as later:
        await maybe_finalize_run(
            session=later,
            user_id=user,
            run_id=run_id,
            tech_news_cluster_sender=sent.append,
        )
        await later.commit()
        assert await _cluster_claimed_at(later, run_id) is not None

    assert len(sent) == 1


async def test_tech_news_cluster_claim_rolls_back_with_failed_send(
    file_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A failed SQS send releases the claim so the next finalize re-dispatches.

    A claim that outlived the send would leave ``pending_clusters`` stuck.
    """
    async with file_sessionmaker() as session:
        user, run_id = await _seed_newsletter_run(session)
        await session.commit()

    def _failing_send(_message: TechNewsClusterMessage) -> None:
        raise RuntimeError("sqs unavailable")

    async with file_sessionmaker() as failing:
        with pytest.raises(RuntimeError, match="sqs unavailable"):
            await maybe_finalize_run(
                session=failing,
                user_id=user,
                run_id=run_id,
                tech_news_cluster_sender=_failing_send,
            )
        await failing.rollback()

    sent: list[TechNewsClusterMessage] = []
    async with file_sessionmaker() as retry:
        assert await _cluster_claimed_at(retry, run_id) is None
        await maybe_finalize_run(
            session=retry,
            user_id=user,
            run_id=run_id,
            tech_news_cluster_sender=sent.append,
        )
        await retry.commit()

    assert len(sent) == 1


async def test_maybe_finalize_run_skips_clusters_when_clustering_disabled(
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With clustering off, newsletters neither dispatch nor block completion."""
    monkeypatch.setattr("app.services.runs._NEWSLETTER_CLUSTERING_ENABLED", False)
    user, account, run = await _seed_run(test_session)
    newsletters = [_email(account=account, subject=f"Newsletter {idx}") for idx in range(2)]
    test_session.add_all(newsletters)
    await test_session.flush()
    await stamp_run_membership(
        session=test_session,
        run_id=run.id,
        email_ids=(email.id for email in newsletters),
    )
    for email in newsletters:
        test_session.add_all(
            [
                _classification(email, is_newsletter=True),
                Summary(
                    kind="email",
                    email_id=email.id,
                    cluster_id=None,
                    prompt_version_id=None,
                    model="gemini-1.5-flash",
                    tokens_in=10,
                    tokens_out=5,
                    body_md_ct=b"summary",
                    entities_ct=None,
                    cache_hit=False,
                    confidence=Decimal("0.900"),
                ),
            ],
        )
    await test_session.flush()
    sent: list[TechNewsClusterMessage] = []

    terminal = await maybe_finalize_run(
        session=test_session,
        user_id=user.id,
        run_id=run.id,
        tech_news_cluster_sender=sent.append,
    )

    assert terminal is True
    assert run.status == "complete"
    assert sent == []


async def _seed_newsletter_run(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a run whose two member newsletters are both classified.

    Returns:
        ``(user_id, run_id)``.
    """
    user, account, run = await _seed_run(session)
    newsletters = [_email(account=account, subject=f"Newsletter {idx}") for idx in range(2)]
    session.add_all(newsletters)
    await session.flush()
    await stamp_run_membership(
        session=session,
        run_id=run.id,
        email_ids=(email.id for email in newsletters),
    )
    session.add_all([_classification(email, is_newsletter=True) for email in newsletters])
    await session.flush()
    return user.id, run.id


async def _cluster_claimed_at(session: AsyncSession, run_id: uuid.UUID) -> datetime | None:
    """Read the committed cluster claim, bypassing the session's identity map."""
    return (
        await session.execute(
            select(DigestRun.tech_news_cluster_enqueued_at)
            .where(DigestRun.id == run_id)
            .execution_options(populate_existing=True),
        )
    ).scalar_one()


def _classification(email: Email, *, is_newsletter: bool) -> Classification:
    """Build an ``ignore`` classification, optionally flagged as a newsletter."""
    return Classification(
        email_id=email.id,
        label="ignore",
        score=Decimal("0.800"),
        rubric_version=1,
        decision_source="model",
        model="gemini-1.5-flash",
        tokens_in=10,
        tokens_out=5,
        is_newsletter=is_newsletter,
    )


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
        labels=["UNREAD"],
        content_hash=digest,
        size_bytes=42,
    )
