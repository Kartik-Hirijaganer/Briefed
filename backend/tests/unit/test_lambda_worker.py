"""Smoke tests for the Lambda worker dispatcher + fan-out shims."""

from __future__ import annotations

import uuid
from types import TracebackType
from typing import Any

import pytest

from app.lambda_worker import (
    _build_redaction_chain_for_user,
    _handle_classify_record,
    _handle_ingest_record,
    _handle_summarize_record,
    fanout_handler,
    sqs_dispatcher,
)
from app.lambda_worker import _SqsEvent as SqsEvent
from app.llm.redaction import IdentityScrubber, RegexSanitizer
from app.services.ingestion.pipeline import IngestStats
from app.workers.messages import (
    CategoryDigestMessage,
    ClassifyMessage,
    IngestMessage,
    SummarizeEmailMessage,
)


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


async def test_handle_ingest_record_commits_before_enqueueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ingested rows commit before any classify / summarize message is sent.

    Otherwise a fast classify worker raises ``LookupError`` on the
    uncommitted email.
    """
    events: list[str] = []
    sqs = _FakeSqs(events)
    _install_worker_stubs(monkeypatch, session=_FakeSession(events), sqs=sqs)

    async def _handle_ingest(*_args: Any, **_kwargs: Any) -> IngestStats:
        events.append("ingest")
        return IngestStats(
            new=2,
            duplicates=0,
            divergent=0,
            raw_uploaded=0,
            cursor_stale=False,
            email_ids=(uuid.uuid4(), uuid.uuid4()),
        )

    monkeypatch.setattr("app.workers.handlers.ingest.handle_ingest", _handle_ingest)
    monkeypatch.setattr(
        "app.services.classification.dispatch.enqueue_unclassified_for_account",
        _fake_enqueue,
    )
    monkeypatch.setattr("app.services.summarization.enqueue_unsummarized_for_run", _fake_enqueue)

    message = IngestMessage(user_id=uuid.uuid4(), account_id=uuid.uuid4(), run_id=uuid.uuid4())
    await _handle_ingest_record({"body": message.model_dump_json()})

    assert events == [
        "ingest",
        "commit",
        "send:classify",
        "send:summarize",
        "send:summarize",  # category digest from maybe_finalize_run
        "commit",
    ]
    assert sqs.clients_built == 1


@pytest.mark.parametrize(
    ("run_id", "expected_sends"),
    [
        (uuid.uuid4(), ["send:classify", "send:summarize", "send:summarize"]),
        (None, ["send:summarize"]),
    ],
    ids=["run-scoped", "ad-hoc"],
)
async def test_handle_ingest_record_rescans_run_backlog_without_new_mail(
    monkeypatch: pytest.MonkeyPatch,
    run_id: uuid.UUID | None,
    expected_sends: list[str],
) -> None:
    """A run-scoped ingest re-enqueues the classify backlog with no new mail.

    A retry after a failed send ingests nothing new, so this scan recovers
    the first attempt's emails. Ad-hoc ingests keep the new-mail gate.
    """
    events: list[str] = []
    _install_worker_stubs(monkeypatch, session=_FakeSession(events), sqs=_FakeSqs(events))

    async def _handle_ingest(*_args: Any, **_kwargs: Any) -> IngestStats:
        return IngestStats(new=0, duplicates=0, divergent=0, raw_uploaded=0, cursor_stale=False)

    monkeypatch.setattr("app.workers.handlers.ingest.handle_ingest", _handle_ingest)
    monkeypatch.setattr(
        "app.services.classification.dispatch.enqueue_unclassified_for_account",
        _fake_enqueue,
    )
    monkeypatch.setattr("app.services.summarization.enqueue_unsummarized_for_run", _fake_enqueue)

    message = IngestMessage(user_id=uuid.uuid4(), account_id=uuid.uuid4(), run_id=run_id)
    await _handle_ingest_record({"body": message.model_dump_json()})

    assert [event for event in events if event.startswith("send:")] == expected_sends
    assert events.index("commit") < events.index(expected_sends[0])


async def test_handle_classify_record_commits_before_enqueueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The classification commits before summarize / hygiene / digest sends."""
    events: list[str] = []
    _install_worker_stubs(monkeypatch, session=_FakeSession(events), sqs=_FakeSqs(events))
    _install_llm_stubs(monkeypatch)
    monkeypatch.setenv("BRIEFED_UNSUBSCRIBE_QUEUE_URL", "https://sqs.example/unsubscribe")

    async def _handle_classify(*_args: Any, **_kwargs: Any) -> None:
        events.append("classify")

    async def _mark_hygiene_enqueued(**_kwargs: Any) -> bool:
        return True

    async def _no_cluster_job(**_kwargs: Any) -> int:
        return 0

    monkeypatch.setattr("app.workers.handlers.classify.handle_classify", _handle_classify)
    monkeypatch.setattr("app.services.summarization.enqueue_summary_for_email", _fake_enqueue)
    monkeypatch.setattr(
        "app.services.summarization.enqueue_tech_news_cluster_for_account",
        _no_cluster_job,
    )
    monkeypatch.setattr(
        "app.services.unsubscribe.dispatch.enqueue_hygiene_run_for_account",
        _fake_enqueue,
    )
    monkeypatch.setattr(
        "app.services.runs.mark_unsubscribe_hygiene_enqueued",
        _mark_hygiene_enqueued,
    )

    message = ClassifyMessage(
        user_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
    )
    await _handle_classify_record({"body": message.model_dump_json()})

    assert events == [
        "classify",
        "commit",
        "send:summarize",  # per-email summary
        "send:unsubscribe",
        "send:summarize",  # category digest from maybe_finalize_run
        "commit",
    ]


async def test_handle_summarize_record_commits_before_category_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The email summary commits before finalize can send a category digest.

    The category-digest worker raises ``CategoryDigestNotReadyError``
    while any member summary is still uncommitted.
    """
    events: list[str] = []
    _install_worker_stubs(monkeypatch, session=_FakeSession(events), sqs=_FakeSqs(events))
    _install_llm_stubs(monkeypatch)

    async def _handle_summarize_email(*_args: Any, **_kwargs: Any) -> None:
        events.append("summarize")

    monkeypatch.setattr(
        "app.workers.handlers.summarize.handle_summarize_email",
        _handle_summarize_email,
    )

    message = SummarizeEmailMessage(
        user_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
    )
    await _handle_summarize_record({"body": message.model_dump_json()})

    assert events == ["summarize", "commit", "send:summarize", "commit"]


def _install_worker_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session: _FakeSession,
    sqs: _FakeSqs,
) -> None:
    """Stub the AWS clients, sessionmaker, and run bookkeeping every stage uses."""
    monkeypatch.setenv("BRIEFED_TOKEN_WRAP_KEY_ALIAS", "alias/token")
    monkeypatch.setenv("BRIEFED_CONTENT_KEY_ALIAS", "alias/content")
    monkeypatch.setenv("BRIEFED_CLASSIFY_QUEUE_URL", "https://sqs.example/classify")
    monkeypatch.setenv("BRIEFED_SUMMARIZE_QUEUE_URL", "https://sqs.example/summarize")

    def _sqs_client() -> _FakeSqs:
        sqs.clients_built += 1
        return sqs

    async def _mark_run_running(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _maybe_finalize_run(**kwargs: Any) -> bool:
        # Mirrors the real helper: no run → nothing to finalize or digest.
        sender = kwargs["category_digest_sender"]
        if sender is not None and kwargs["run_id"] is not None:
            sender(CategoryDigestMessage(run_id=kwargs["run_id"], category="must_read"))
        return False

    monkeypatch.setattr("app.lambda_worker._kms_client", object)
    monkeypatch.setattr("app.lambda_worker._sqs_client", _sqs_client)
    monkeypatch.setattr("app.db.session.get_sessionmaker", lambda: _FakeSessionmaker(session))
    monkeypatch.setattr("app.services.runs.mark_run_running", _mark_run_running)
    monkeypatch.setattr("app.services.runs.maybe_finalize_run", _maybe_finalize_run)


def _install_llm_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the LLM client, redaction chain, and prompt registry."""

    async def _redaction_chain(*_args: Any, **_kwargs: Any) -> object:
        return object()

    monkeypatch.setattr("app.lambda_worker._build_redaction_chain_for_user", _redaction_chain)
    monkeypatch.setattr("app.llm.factory.build_llm_client", lambda **_kwargs: object())
    monkeypatch.setattr("app.services.prompts.registry.PromptRegistry", _FakeRegistry)


async def _fake_enqueue(**kwargs: Any) -> int:
    """Stand in for a dispatch helper: send one message to ``queue_url``."""
    kwargs["sqs"].send_message(QueueUrl=kwargs["queue_url"], MessageBody="{}")
    return 1


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
    """SQS stand-in that logs each send by destination queue name."""

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.clients_built = 0

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, Any]:
        """Record the send as ``send:<queue name>``."""
        self._events.append(f"send:{QueueUrl.rsplit('/', 1)[-1]}")
        return {"MessageId": "fake"}


class _FakeSession:
    """Async session stand-in that logs commits into the shared event list."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def commit(self) -> None:
        """Record the commit call."""
        self._events.append("commit")


class _FakeRegistry:
    """Prompt registry stand-in whose DB sync is a no-op."""

    @classmethod
    def load(cls) -> _FakeRegistry:
        """Return a fresh stub registry."""
        return cls()

    async def sync_to_db(self, _session: Any) -> None:
        """Skip the prompt_versions upsert."""


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
    # Identity scrubber present; regex remains the fallback sanitizer.
    assert any(isinstance(s, IdentityScrubber) for s in chain.sanitizers)
    assert any(isinstance(s, RegexSanitizer) for s in chain.sanitizers)
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
