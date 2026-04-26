"""Chaos drill — DLQ depth (plan §14 Phase 8 + §16).

Verifies the SQS dispatcher returns a partial-batch failure for a
poison record so SQS will redrive it to the DLQ on max-receive. The
DLQ alarm in `infra/terraform/modules/alarms` then fires the SNS
notification.
"""

from __future__ import annotations

import pytest

from app.lambda_worker import sqs_dispatcher

pytestmark = pytest.mark.chaos


def _poison_record(stage: str = "ingest") -> dict[str, str]:
    return {
        "messageId": "drill-1",
        "eventSourceARN": f"arn:aws:sqs:us-east-1:000:briefed-dev-{stage}",
        # Body is invalid JSON for every parser registered in the dispatcher.
        "body": "{this is not parseable]]",
    }


def test_dispatcher_redrives_poison_record() -> None:
    response = sqs_dispatcher({"Records": [_poison_record()]}, None)
    failures = response["batchItemFailures"]
    assert failures == [{"itemIdentifier": "drill-1"}], (
        "poison record must be redriven so the DLQ alarm can fire"
    )


def test_dispatcher_isolates_failures_in_batch() -> None:
    """A failing record does not poison its successful neighbours."""
    response = sqs_dispatcher(
        {
            "Records": [
                _poison_record(),
                # Unknown stage — dispatcher logs warning, treats as success.
                {
                    "messageId": "good-1",
                    "eventSourceARN": "arn:aws:sqs:us-east-1:000:briefed-dev-mystery",
                    "body": "{}",
                },
            ],
        },
        None,
    )
    failures = response["batchItemFailures"]
    ids = [f["itemIdentifier"] for f in failures]
    assert "drill-1" in ids
    assert "good-1" not in ids
