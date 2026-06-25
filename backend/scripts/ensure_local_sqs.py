"""Ensure LocalStack SQS queues required by local development exist."""

from __future__ import annotations

import os
import shlex
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, TypedDict, cast

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
)
from pydantic import BaseModel, ConfigDict, Field

_MAX_ATTEMPTS = 30
"""Maximum LocalStack readiness attempts before failing."""

_DEFAULT_ENV_FILE = ".artifacts/local-sqs.env"
"""Default shell env file populated for ``make dev``."""

_QUEUE_ATTRIBUTES: dict[str, str] = {
    "MessageRetentionPeriod": "345600",
    "VisibilityTimeout": "900",
}
"""Local queue attributes matching the Lambda worker timeout envelope."""


class QueueSpec(BaseModel):
    """Local SQS queue binding written into the generated env file.

    Attributes:
        env_var: Environment variable name consumed by API and worker processes.
        queue_name: LocalStack queue name.
    """

    model_config = ConfigDict(frozen=True)

    env_var: str = Field(..., description="Environment variable populated with the queue URL.")
    queue_name: str = Field(..., description="LocalStack queue name.")


_QUEUES: tuple[QueueSpec, ...] = (
    QueueSpec(env_var="BRIEFED_INGEST_QUEUE_URL", queue_name="briefed-dev-ingest"),
    QueueSpec(env_var="BRIEFED_CLASSIFY_QUEUE_URL", queue_name="briefed-dev-classify"),
    QueueSpec(env_var="BRIEFED_SUMMARIZE_QUEUE_URL", queue_name="briefed-dev-summarize"),
    QueueSpec(env_var="BRIEFED_UNSUBSCRIBE_QUEUE_URL", queue_name="briefed-dev-unsubscribe"),
)
"""Queues used by the local end-to-end scan pipeline."""


class _GetQueueUrlResponse(TypedDict):
    """Subset of the SQS ``get_queue_url`` response used by this script."""

    QueueUrl: str


class _CreateQueueResponse(TypedDict):
    """Subset of the SQS ``create_queue`` response used by this script."""

    QueueUrl: str


class _SqsClient(Protocol):
    """Protocol for the SQS client surface used here."""

    def get_queue_url(self, *, QueueName: str) -> _GetQueueUrlResponse:  # noqa: N803
        """Return the URL for an existing queue.

        Args:
            QueueName: Queue name to resolve.

        Returns:
            Queue URL response.
        """

    def create_queue(
        self,
        *,
        QueueName: str,  # noqa: N803
        Attributes: Mapping[str, str],  # noqa: N803
    ) -> _CreateQueueResponse:
        """Create a queue.

        Args:
            QueueName: Queue name to create.
            Attributes: Queue attributes for LocalStack.

        Returns:
            Created queue response.
        """

    def set_queue_attributes(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        Attributes: Mapping[str, str],  # noqa: N803
    ) -> None:
        """Set attributes on an existing queue.

        Args:
            QueueUrl: Queue URL to configure.
            Attributes: Queue attributes for LocalStack.
        """


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


def _is_missing_queue_error(exc: ClientError) -> bool:
    """Return whether a client error means the queue does not exist.

    Args:
        exc: Boto client error raised by ``get_queue_url``.

    Returns:
        ``True`` when LocalStack/SQS reported a missing queue.
    """
    error = cast("Mapping[str, object]", exc.response.get("Error", {}))
    code = str(error.get("Code", ""))
    return code in {
        "AWS.SimpleQueueService.NonExistentQueue",
        "QueueDoesNotExist",
    }


def _ensure_queue(client: _SqsClient, spec: QueueSpec) -> str:
    """Return an existing queue URL, creating the queue when absent.

    Args:
        client: LocalStack SQS client.
        spec: Queue binding to ensure.

    Returns:
        Queue URL.

    Raises:
        ClientError: If SQS rejects the request for any reason other than
            a missing queue.
    """
    try:
        response = client.get_queue_url(QueueName=spec.queue_name)
        print(f"{spec.queue_name} exists")
        queue_url = response["QueueUrl"]
    except ClientError as exc:
        if not _is_missing_queue_error(exc):
            raise
        response = client.create_queue(QueueName=spec.queue_name, Attributes=_QUEUE_ATTRIBUTES)
        print(f"{spec.queue_name} created")
        queue_url = response["QueueUrl"]
    client.set_queue_attributes(QueueUrl=queue_url, Attributes=_QUEUE_ATTRIBUTES)
    return queue_url


def _write_env_file(path: Path, assignments: Mapping[str, str]) -> None:
    """Write shell-compatible queue URL assignments.

    Args:
        path: Destination env file path.
        assignments: Environment variable names and values to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{name}={shlex.quote(value)}" for name, value in sorted(assignments.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ensure_queues(client: _SqsClient) -> dict[str, str]:
    """Ensure all local pipeline queues exist.

    Args:
        client: LocalStack SQS client.

    Returns:
        Mapping from env var name to queue URL.
    """
    return {spec.env_var: _ensure_queue(client, spec) for spec in _QUEUES}


def main() -> None:
    """Wait for LocalStack and write local queue URLs for Make targets.

    Raises:
        SystemExit: If LocalStack SQS is not reachable after retrying.
    """
    client = _build_client()
    env_file = Path(os.environ.get("BRIEFED_LOCAL_SQS_ENV_FILE", _DEFAULT_ENV_FILE))
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            assignments = _ensure_queues(client)
            _write_env_file(env_file, assignments)
            print(f"wrote {env_file}")
            return
        except (BotoCoreError, ClientError, EndpointConnectionError) as exc:
            if attempt == _MAX_ATTEMPTS:
                raise SystemExit(f"LocalStack SQS did not become ready: {exc}") from exc
            time.sleep(1)


if __name__ == "__main__":
    main()
