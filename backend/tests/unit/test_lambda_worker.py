"""Smoke tests for the Phase 0 Lambda worker stubs."""

from app.lambda_worker import fanout_handler, sqs_dispatcher


def test_sqs_dispatcher_empty_batch_reports_no_failures() -> None:
    result = sqs_dispatcher({"Records": []}, None)
    assert result == {"batchItemFailures": []}


def test_sqs_dispatcher_single_record_is_acked() -> None:
    event = {
        "Records": [
            {
                "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:briefed-dev-ingest",
                "messageId": "m-1",
                "body": "{}",
            }
        ]
    }
    result = sqs_dispatcher(event, None)
    assert result["batchItemFailures"] == []


def test_fanout_handler_stub_returns_zero() -> None:
    assert fanout_handler({}, None) == {"accounts_enqueued": 0}
