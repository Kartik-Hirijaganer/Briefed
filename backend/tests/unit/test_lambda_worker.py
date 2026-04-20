"""Smoke tests for the Lambda worker dispatcher + fan-out shims."""

from __future__ import annotations

from app.lambda_worker import fanout_handler, sqs_dispatcher


def test_sqs_dispatcher_empty_batch_reports_no_failures() -> None:
    result = sqs_dispatcher({"Records": []}, None)
    assert result == {"batchItemFailures": []}


def test_sqs_dispatcher_reports_failure_on_bad_body() -> None:
    event = {
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
    event = {
        "Records": [
            {
                "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:briefed-dev-classify",
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
