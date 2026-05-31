"""Smoke tests for the Lambda worker dispatcher + fan-out shims."""

from __future__ import annotations

import uuid
from types import TracebackType
from typing import Any

import pytest

from app.lambda_worker import (
    _build_redaction_chain_for_user,
    _handle_ingest_record,
    fanout_handler,
    sqs_dispatcher,
)
from app.lambda_worker import _SqsEvent as SqsEvent
from app.llm.redaction import IdentityScrubber, PresidioSanitizer
from app.services.ingestion.pipeline import IngestStats
from app.workers.messages import IngestMessage


def test_sqs_dispatcher_empty_batch_reports_no_failures() -> None:
    result = sqs_dispatcher({"Records": []}, None)
    assert result == {"batchItemFailures": []}


def test_sqs_dispatcher_reports_failure_on_bad_body() -> None:
    event: SqsEvent = {
        "Records": [
            {
                "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:briefed-dev-ingest",
                "messageId": "m-1",
                "body": "{}",  # missing required user_id / account_id
            }
        ]
    }
    result = sqs_dispatcher(event, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}


def test_sqs_dispatcher_acks_unknown_stage() -> None:
    event: SqsEvent = {
        "Records": [
            {
                "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:briefed-dev-mystery",
                "messageId": "m-2",
                "body": "{}",
            }
        ]
    }
    result = sqs_dispatcher(event, None)
    assert result == {"batchItemFailures": []}


def test_fanout_handler_returns_zero_when_queue_url_unset(
    monkeypatch: object,
) -> None:
    import os

    # Explicit unset so the handler hits its early-return branch.
    assert not os.environ.get("BRIEFED_INGEST_QUEUE_URL")
    assert fanout_handler({}, None) == {"accounts_enqueued": 0}


async def test_handle_ingest_record_requeues_downstream_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ingest requeues already-classified rows even when no new mail arrives."""
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    run_id = uuid.uuid4()
    fake_session = _FakeSession()
    sqs = _FakeSqs()
    sqs_creations = 0
    calls: list[tuple[str, str]] = []

    async def _handle_ingest(*_args: Any, **_kwargs: Any) -> IngestStats:
        return IngestStats(
            new=0,
            duplicates=3,
            divergent=0,
            raw_uploaded=0,
            cursor_stale=False,
        )

    async def _enqueue_classify(**kwargs: Any) -> int:
        calls.append(("classify", kwargs["queue_url"]))
        return 1

    async def _enqueue_summary(**kwargs: Any) -> tuple[int, int]:
        calls.append(("summary", kwargs["queue_url"]))
        return 2, 1

    async def _enqueue_jobs(**kwargs: Any) -> int:
        calls.append(("jobs", kwargs["queue_url"]))
        return 1

    monkeypatch.setenv("BRIEFED_TOKEN_WRAP_KEY_ALIAS", "alias/token")
    monkeypatch.setenv("BRIEFED_CONTENT_KEY_ALIAS", "alias/content")
    monkeypatch.setenv("BRIEFED_CLASSIFY_QUEUE_URL", "https://sqs.example/classify")
    monkeypatch.setenv("BRIEFED_SUMMARIZE_QUEUE_URL", "https://sqs.example/summarize")
    monkeypatch.setenv("BRIEFED_JOBS_QUEUE_URL", "https://sqs.example/jobs")

    def _kms_client() -> object:
        return object()

    monkeypatch.setattr("app.lambda_worker._kms_client", _kms_client)

    def _sqs_client() -> _FakeSqs:
        nonlocal sqs_creations
        sqs_creations += 1
        return sqs

    monkeypatch.setattr("app.lambda_worker._sqs_client", _sqs_client)
    monkeypatch.setattr(
        "app.db.session.get_sessionmaker",
        lambda: _FakeSessionmaker(fake_session),
    )
    monkeypatch.setattr("app.workers.handlers.ingest.handle_ingest", _handle_ingest)
    monkeypatch.setattr(
        "app.services.classification.dispatch.enqueue_unclassified_for_account",
        _enqueue_classify,
    )
    monkeypatch.setattr(
        "app.services.summarization.enqueue_unsummarized_for_run",
        _enqueue_summary,
    )
    monkeypatch.setattr(
        "app.services.jobs.dispatch.enqueue_unextracted_for_account",
        _enqueue_jobs,
    )

    message = IngestMessage(user_id=user_id, account_id=account_id, run_id=run_id)
    await _handle_ingest_record({"body": message.model_dump_json()})

    assert calls == [
        ("summary", "https://sqs.example/summarize"),
        ("jobs", "https://sqs.example/jobs"),
    ]
    assert sqs_creations == 1
    assert fake_session.committed is True


class _StubUser:
    """Minimal stand-in for :class:`app.db.models.User`."""

    def __init__(
        self,
        *,
        email: str,
        display_name: str | None,
        email_aliases: list[str],
        redaction_aliases: list[str],
        presidio_enabled: bool,
    ) -> None:
        self.email = email
        self.display_name = display_name
        self.email_aliases = email_aliases
        self.redaction_aliases = redaction_aliases
        self.presidio_enabled = presidio_enabled


class _StubSession:
    """Async session stand-in whose ``get`` returns a pre-seeded user."""

    def __init__(self, user: Any) -> None:
        self._user = user
        self.last_args: tuple[Any, Any] | None = None

    async def get(self, model: Any, ident: Any) -> Any:
        self.last_args = (model, ident)
        return self._user


class _FakeSqs:
    """Fake SQS factory result used to verify lazy client creation."""

    def __init__(self) -> None:
        self.created = 1


class _FakeSession:
    """Async session stand-in with a visible commit marker."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        """Record the commit call."""
        self.committed = True


class _FakeSessionContext:
    """Context manager returned by the fake sessionmaker."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        """Return the fake session."""
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Mirror AsyncSession context manager exit."""


class _FakeSessionmaker:
    """Callable async context factory matching SQLAlchemy's sessionmaker."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSessionContext:
        """Return a new fake context for the same session."""
        return _FakeSessionContext(self._session)


async def test_build_redaction_chain_for_user_uses_profile_fields() -> None:
    """Track B Phase 7 — chain reads from the user-profile row."""
    user = _StubUser(
        email="me@example.com",
        display_name="Real Name",
        email_aliases=["alias@example.com"],
        redaction_aliases=["Nickname"],
        presidio_enabled=False,
    )
    session = _StubSession(user)
    chain = await _build_redaction_chain_for_user(session, uuid.uuid4())
    # Identity scrubber present; Presidio skipped per profile flag.
    assert any(isinstance(s, IdentityScrubber) for s in chain.sanitizers)
    assert all(not isinstance(s, PresidioSanitizer) for s in chain.sanitizers)
    redacted = chain.sanitize(
        "From me@example.com / alias@example.com — signed Nickname",
    )
    assert "me@example.com" not in redacted.text
    assert "alias@example.com" not in redacted.text
    assert "Nickname" not in redacted.text
    assert redacted.counts_by_kind.get("USER_EMAIL") == 2
    assert redacted.counts_by_kind.get("USER_NAME") == 1


async def test_build_redaction_chain_for_user_falls_back_when_missing() -> None:
    """When the user row is gone, fall back to the settings-based chain
    so the worker stays available (test fixtures, deleted users)."""
    session = _StubSession(user=None)
    chain = await _build_redaction_chain_for_user(session, uuid.uuid4())
    # Falls through to _build_redaction_chain — at minimum the regex
    # sanitizer is always present.
    assert chain.sanitizers, "fallback chain should not be empty"
