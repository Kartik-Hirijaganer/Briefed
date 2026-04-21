"""Enqueue + parse unsubscribe-run SQS messages (plan §14 Phase 5).

Two entrypoints:

* :func:`enqueue_hygiene_run_for_account` — called after classification
  lands for a run so the hygiene aggregate fires per account. Emits
  one :class:`app.workers.messages.UnsubscribeMessage` (not per-email;
  the worker does the aggregate itself).
* :func:`parse_unsubscribe_body` — validates a raw SQS body into the
  Pydantic message.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from app.core.logging import get_logger
from app.workers.messages import UnsubscribeMessage

if TYPE_CHECKING:  # pragma: no cover
    pass


logger = get_logger(__name__)


class SqsSender(Protocol):
    """Subset of boto3 SQS we rely on."""

    def send_message(
        self,
        *,
        QueueUrl: str,
        MessageBody: str,
    ) -> dict[str, Any]:
        """Enqueue one SQS message."""
        ...


async def enqueue_hygiene_run_for_account(
    *,
    user_id: UUID,
    account_id: UUID,
    queue_url: str,
    sqs: SqsSender,
    run_id: UUID | None,
    prompt_name: str = "unsubscribe_borderline",
    prompt_version: int = 1,
) -> int:
    """Enqueue one :class:`UnsubscribeMessage` for the given account.

    Unlike the classify / jobs dispatchers, this emits **one** message
    per account per run — the worker itself aggregates across the
    sender universe. Nothing here touches the DB.

    Args:
        user_id: Owning user.
        account_id: Target connected account.
        queue_url: Destination SQS URL.
        sqs: boto3-compatible SQS client.
        run_id: Optional digest-run id.
        prompt_name: Prompt key to carry on the payload.
        prompt_version: Prompt version to carry.

    Returns:
        Count of messages enqueued (always ``1``; returned for
        symmetry with the classify / jobs dispatchers so telemetry
        helpers can treat them uniformly).
    """
    message = UnsubscribeMessage(
        user_id=user_id,
        account_id=account_id,
        run_id=run_id,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
    )
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=message.model_dump_json(),
    )
    logger.info(
        "unsubscribe.dispatch.enqueued",
        account_id=str(account_id),
        run_id=str(run_id) if run_id else None,
    )
    return 1


def parse_unsubscribe_body(body: str) -> UnsubscribeMessage:
    """Validate + parse a raw SQS body into :class:`UnsubscribeMessage`.

    Args:
        body: Raw JSON body string from the SQS event record.

    Returns:
        The validated Pydantic model.

    Raises:
        ValueError: When the JSON is malformed or violates the schema.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON body: {exc}") from exc
    return UnsubscribeMessage.model_validate(payload)


__all__ = [
    "SqsSender",
    "enqueue_hygiene_run_for_account",
    "parse_unsubscribe_body",
]
