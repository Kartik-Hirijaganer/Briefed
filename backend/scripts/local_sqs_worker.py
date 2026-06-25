"""Poll LocalStack SQS queues and invoke the Lambda worker dispatcher locally."""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Mapping
from types import FrameType
from typing import Literal, Protocol, TypedDict, cast

import boto3  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from app.lambda_worker import _SqsEvent as LambdaSqsEvent
from app.lambda_worker import sqs_dispatcher

Stage = Literal["ingest", "classify", "summarize", "unsubscribe"]
"""Supported local pipeline stages."""

_QUEUE_ENV: Mapping[Stage, str] = {
    "ingest": "BRIEFED_INGEST_QUEUE_URL",
    "classify": "BRIEFED_CLASSIFY_QUEUE_URL",
    "summarize": "BRIEFED_SUMMARIZE_QUEUE_URL",
    "unsubscribe": "BRIEFED_UNSUBSCRIBE_QUEUE_URL",
}
"""Environment variables containing LocalStack queue URLs."""

_STOP_REQUESTED = False
"""Process-level stop flag set by signal handlers."""


class QueueConfig(BaseModel):
    """Runtime binding for one local SQS queue.

    Attributes:
        stage: Pipeline stage represented by this queue.
        queue_url: Queue URL used to poll and delete messages.
        event_source_arn: Lambda-style source ARN used by the dispatcher.
    """

    model_config = ConfigDict(frozen=True)

    stage: Stage = Field(..., description="Pipeline stage represented by the queue.")
    queue_url: str = Field(..., description="LocalStack queue URL.")
    event_source_arn: str = Field(..., description="Lambda-compatible SQS event source ARN.")


class _ReceivedMessage(TypedDict, total=False):
    """Subset of an SQS message returned by ``receive_message``."""

    MessageId: str
    ReceiptHandle: str
    Body: str


class _ReceiveMessageResponse(TypedDict, total=False):
    """Subset of the SQS ``receive_message`` response used by this script."""

    Messages: list[_ReceivedMessage]


class _DeleteMessageBatchEntry(TypedDict):
    """SQS batch-delete entry."""

    Id: str
    ReceiptHandle: str


class _SqsRecord(TypedDict):
    """Minimal SQS record passed to the Lambda dispatcher."""

    eventSourceARN: str
    messageId: str
    body: str


class _SqsEvent(TypedDict):
    """Minimal SQS event passed to the Lambda dispatcher."""

    Records: list[_SqsRecord]


class _SqsClient(Protocol):
    """Protocol for the SQS client surface used by the local worker."""

    def receive_message(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        MaxNumberOfMessages: int,  # noqa: N803
        WaitTimeSeconds: int,  # noqa: N803
        AttributeNames: list[str],  # noqa: N803
    ) -> _ReceiveMessageResponse:
        """Receive messages from one queue.

        Args:
            QueueUrl: Queue URL to poll.
            MaxNumberOfMessages: Maximum batch size.
            WaitTimeSeconds: Long-poll wait in seconds.
            AttributeNames: Attributes to request from SQS.

        Returns:
            SQS receive response.
        """

    def delete_message_batch(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        Entries: list[_DeleteMessageBatchEntry],  # noqa: N803
    ) -> object:
        """Delete a batch of successfully processed messages.

        Args:
            QueueUrl: Queue URL containing the messages.
            Entries: Batch delete entries.

        Returns:
            Boto3 delete response.
        """


def _request_stop(_signum: int, _frame: FrameType | None) -> None:
    """Request graceful shutdown on SIGINT/SIGTERM.

    Args:
        _signum: Received signal number.
        _frame: Current interpreter frame.
    """
    global _STOP_REQUESTED  # noqa: PLW0603
    _STOP_REQUESTED = True


def _build_client() -> _SqsClient:
    """Build an SQS client pointed at LocalStack.

    Returns:
        Boto3 SQS client narrowed to the protocol used by this script.
    """
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    region_name = os.environ.get("AWS_REGION", "us-east-1")
    return cast(
        "_SqsClient",
        boto3.client("sqs", endpoint_url=endpoint_url, region_name=region_name),
    )


def _event_source_arn(*, stage: Stage, queue_url: str) -> str:
    """Build the Lambda-style SQS event source ARN for a local queue.

    Args:
        stage: Pipeline stage represented by the queue.
        queue_url: Queue URL whose final path segment is the queue name.

    Returns:
        Event source ARN consumed by ``sqs_dispatcher``.
    """
    region = os.environ.get("AWS_REGION", "us-east-1")
    account_id = os.environ.get("BRIEFED_LOCAL_AWS_ACCOUNT_ID", "000000000000")
    queue_name = queue_url.rstrip("/").rsplit("/", 1)[-1] or f"briefed-dev-{stage}"
    return f"arn:aws:sqs:{region}:{account_id}:{queue_name}"


def _queue_configs() -> tuple[QueueConfig, ...]:
    """Read local queue bindings from environment.

    Returns:
        Queue configurations for each pipeline stage.

    Raises:
        SystemExit: If one or more queue URL environment variables are missing.
    """
    missing: list[str] = []
    configs: list[QueueConfig] = []
    for stage, env_var in _QUEUE_ENV.items():
        queue_url = os.environ.get(env_var)
        if not queue_url:
            missing.append(env_var)
            continue
        configs.append(
            QueueConfig(
                stage=stage,
                queue_url=queue_url,
                event_source_arn=_event_source_arn(stage=stage, queue_url=queue_url),
            )
        )
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing local queue URL env var(s): {joined}")
    return tuple(configs)


def _messages_to_event(*, queue: QueueConfig, messages: list[_ReceivedMessage]) -> _SqsEvent:
    """Convert SQS receive messages into a Lambda event.

    Args:
        queue: Queue configuration for the messages.
        messages: Messages returned by SQS.

    Returns:
        Lambda-compatible SQS event.
    """
    records: list[_SqsRecord] = []
    for index, message in enumerate(messages):
        message_id = message.get("MessageId") or f"{queue.stage}-{index}"
        records.append(
            {
                "eventSourceARN": queue.event_source_arn,
                "messageId": message_id,
                "body": message.get("Body", "{}"),
            }
        )
    return {"Records": records}


def _delete_successful(
    *,
    client: _SqsClient,
    queue: QueueConfig,
    messages: list[_ReceivedMessage],
    failed_ids: set[str],
) -> int:
    """Delete messages not reported as failed by the dispatcher.

    Args:
        client: SQS client.
        queue: Queue configuration for the messages.
        messages: Messages returned by SQS.
        failed_ids: Message ids that should remain visible for retry.

    Returns:
        Number of messages deleted.
    """
    entries: list[_DeleteMessageBatchEntry] = []
    for index, message in enumerate(messages):
        message_id = message.get("MessageId") or f"{queue.stage}-{index}"
        receipt_handle = message.get("ReceiptHandle")
        if not receipt_handle or message_id in failed_ids:
            continue
        entries.append({"Id": str(index), "ReceiptHandle": receipt_handle})
    if not entries:
        return 0
    client.delete_message_batch(QueueUrl=queue.queue_url, Entries=entries)
    return len(entries)


def _poll_once(
    *,
    client: _SqsClient,
    queues: tuple[QueueConfig, ...],
    batch_size: int,
    wait_seconds: int,
) -> int:
    """Poll every stage once and process any visible messages.

    Args:
        client: SQS client.
        queues: Queue configurations to poll.
        batch_size: Maximum messages per receive call.
        wait_seconds: SQS long-poll wait in seconds.

    Returns:
        Number of messages successfully deleted.
    """
    processed = 0
    for queue in queues:
        response = client.receive_message(
            QueueUrl=queue.queue_url,
            MaxNumberOfMessages=batch_size,
            WaitTimeSeconds=wait_seconds,
            AttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        if not messages:
            continue
        event = cast("LambdaSqsEvent", _messages_to_event(queue=queue, messages=messages))
        result = sqs_dispatcher(event, None)
        failed_ids = {failure["itemIdentifier"] for failure in result["batchItemFailures"]}
        deleted = _delete_successful(
            client=client,
            queue=queue,
            messages=messages,
            failed_ids=failed_ids,
        )
        processed += deleted
        if failed_ids:
            print(
                f"local_sqs_worker: {queue.stage} failed {len(failed_ids)} message(s): "
                f"{', '.join(sorted(failed_ids))}"
            )
    return processed


def run() -> None:
    """Run the LocalStack SQS worker loop until interrupted."""
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    queues = _queue_configs()
    client = _build_client()
    batch_size = int(os.environ.get("BRIEFED_LOCAL_WORKER_BATCH_SIZE", "10"))
    wait_seconds = int(os.environ.get("BRIEFED_LOCAL_WORKER_WAIT_SECONDS", "2"))
    idle_sleep_seconds = float(os.environ.get("BRIEFED_LOCAL_WORKER_IDLE_SLEEP_SECONDS", "0.25"))
    once = os.environ.get("BRIEFED_LOCAL_WORKER_ONCE", "0") == "1"
    print("local_sqs_worker: polling LocalStack queues")
    while not _STOP_REQUESTED:
        processed = _poll_once(
            client=client,
            queues=queues,
            batch_size=batch_size,
            wait_seconds=wait_seconds,
        )
        if once:
            return
        if processed == 0:
            time.sleep(idle_sleep_seconds)


if __name__ == "__main__":
    run()
