"""Smoke tests for the Lambda worker dispatcher + fan-out shims."""

from __future__ import annotations

import uuid
from typing import Any

from app.lambda_worker import (
    _build_redaction_chain_for_user,
    fanout_handler,
    sqs_dispatcher,
)
from app.lambda_worker import _SqsEvent as SqsEvent
from app.llm.redaction import IdentityScrubber, PresidioSanitizer


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
