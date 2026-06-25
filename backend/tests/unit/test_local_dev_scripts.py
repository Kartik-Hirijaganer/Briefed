"""Unit tests for local development SQS helper scripts."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from scripts.ensure_local_sqs import _write_env_file
from scripts.local_sqs_worker import (
    QueueConfig,
    _delete_successful,
    _DeleteMessageBatchEntry,
    _messages_to_event,
    _queue_configs,
    _ReceiveMessageResponse,
    _SqsClient,
)


class _DeleteOnlySqs:
    """Fake SQS client that records batch deletes."""

    def __init__(self) -> None:
        self.deleted: list[tuple[str, list[_DeleteMessageBatchEntry]]] = []

    def receive_message(
        self,
        *,
        QueueUrl: str,
        MaxNumberOfMessages: int,
        WaitTimeSeconds: int,
        AttributeNames: list[str],
    ) -> _ReceiveMessageResponse:
        """Return no messages; included to satisfy the local SQS protocol.

        Args:
            QueueUrl: Queue URL to poll.
            MaxNumberOfMessages: Maximum batch size.
            WaitTimeSeconds: Long-poll wait in seconds.
            AttributeNames: Attributes requested from SQS.

        Returns:
            Empty receive response.
        """
        _ = (QueueUrl, MaxNumberOfMessages, WaitTimeSeconds, AttributeNames)
        return {}

    def delete_message_batch(
        self,
        *,
        QueueUrl: str,
        Entries: list[_DeleteMessageBatchEntry],
    ) -> object:
        """Record successful message deletions.

        Args:
            QueueUrl: Queue URL containing the messages.
            Entries: Batch delete entries.

        Returns:
            Empty delete response.
        """
        self.deleted.append((QueueUrl, Entries))
        return {}


def test_write_env_file_quotes_queue_urls(tmp_path: Path) -> None:
    """Env file output is safe to source from a shell."""
    env_file = tmp_path / "local-sqs.env"

    _write_env_file(env_file, {"BRIEFED_INGEST_QUEUE_URL": "http://localhost/queue?a=1&b=2"})

    assert env_file.read_text(encoding="utf-8") == (
        "BRIEFED_INGEST_QUEUE_URL='http://localhost/queue?a=1&b=2'\n"
    )


def test_queue_configs_build_lambda_source_arns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Queue configs expose Lambda-style ARNs for dispatcher routing."""
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("BRIEFED_INGEST_QUEUE_URL", "http://localhost/briefed-dev-ingest")
    monkeypatch.setenv("BRIEFED_CLASSIFY_QUEUE_URL", "http://localhost/briefed-dev-classify")
    monkeypatch.setenv("BRIEFED_SUMMARIZE_QUEUE_URL", "http://localhost/briefed-dev-summarize")
    monkeypatch.setenv(
        "BRIEFED_UNSUBSCRIBE_QUEUE_URL",
        "http://localhost/briefed-dev-unsubscribe",
    )

    configs = _queue_configs()

    assert configs[0].stage == "ingest"
    assert configs[0].event_source_arn == ("arn:aws:sqs:us-west-2:000000000000:briefed-dev-ingest")


def test_messages_to_event_uses_queue_stage_arn() -> None:
    """Received SQS messages become dispatcher-compatible event records."""
    queue = QueueConfig(
        stage="classify",
        queue_url="http://localhost/briefed-dev-classify",
        event_source_arn="arn:aws:sqs:us-east-1:000000000000:briefed-dev-classify",
    )

    event = _messages_to_event(
        queue=queue,
        messages=[{"MessageId": "m-1", "ReceiptHandle": "r-1", "Body": '{"kind":"classify"}'}],
    )

    assert event == {
        "Records": [
            {
                "eventSourceARN": "arn:aws:sqs:us-east-1:000000000000:briefed-dev-classify",
                "messageId": "m-1",
                "body": '{"kind":"classify"}',
            }
        ]
    }


def test_delete_successful_leaves_failed_messages_visible() -> None:
    """Worker acknowledgements delete only dispatcher-successful messages."""
    client = _DeleteOnlySqs()
    queue = QueueConfig(
        stage="ingest",
        queue_url="http://localhost/briefed-dev-ingest",
        event_source_arn="arn:aws:sqs:us-east-1:000000000000:briefed-dev-ingest",
    )

    deleted = _delete_successful(
        client=cast("_SqsClient", client),
        queue=queue,
        messages=[
            {"MessageId": "m-1", "ReceiptHandle": "r-1", "Body": "{}"},
            {"MessageId": "m-2", "ReceiptHandle": "r-2", "Body": "{}"},
        ],
        failed_ids={"m-2"},
    )

    assert deleted == 1
    assert client.deleted == [
        ("http://localhost/briefed-dev-ingest", [{"Id": "0", "ReceiptHandle": "r-1"}])
    ]
