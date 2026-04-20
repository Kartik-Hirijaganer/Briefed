"""Enqueue ``ClassifyMessage`` payloads for un-classified emails.

Called from the ingest worker once ingestion completes so every new
email lands on the classify queue. Also safe to call during Phase 2
bootstrap to back-fill rows historically ingested.

Kept separate from :mod:`app.services.classification.pipeline` so the
SQS dependency stays at the worker edge and the pipeline itself is
pure-functional for the eval harness.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import Classification, Email
from app.workers.messages import ClassifyMessage

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


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


async def enqueue_unclassified_for_account(
    *,
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    queue_url: str,
    sqs: SqsSender,
    run_id: UUID | None,
    prompt_name: str = "triage",
    prompt_version: int = 1,
    limit: int = 500,
) -> int:
    """Enqueue one :class:`ClassifyMessage` per un-classified email.

    Args:
        session: Active async session.
        user_id: Owning user.
        account_id: Account the emails belong to.
        queue_url: Destination SQS queue URL.
        sqs: boto3-compatible SQS client.
        run_id: Optional digest-run id.
        prompt_name: Prompt key to carry on the payload.
        prompt_version: Prompt version to carry.
        limit: Safety cap per call — prevents unbounded enqueue on a
            fresh install; callers can iterate.

    Returns:
        Count of messages enqueued.
    """
    stmt = (
        select(Email.id)
        .outerjoin(Classification, Classification.email_id == Email.id)
        .where(
            Email.account_id == account_id,
            Classification.email_id.is_(None),
        )
        .order_by(Email.internal_date.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()

    enqueued = 0
    for email_id in rows:
        message = ClassifyMessage(
            user_id=user_id,
            account_id=account_id,
            email_id=email_id,
            run_id=run_id,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=message.model_dump_json(),
        )
        enqueued += 1

    logger.info(
        "classify.dispatch.enqueued",
        account_id=str(account_id),
        run_id=str(run_id) if run_id else None,
        enqueued=enqueued,
    )
    return enqueued


def parse_classify_body(body: str) -> ClassifyMessage:
    """Validate + parse a raw SQS message body into :class:`ClassifyMessage`.

    Args:
        body: Body string from the SQS event record.

    Returns:
        The validated Pydantic model.

    Raises:
        ValueError: When the JSON is malformed or violates the schema.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON body: {exc}") from exc
    return ClassifyMessage.model_validate(payload)


__all__ = ["enqueue_unclassified_for_account", "parse_classify_body"]
