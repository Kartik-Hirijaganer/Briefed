"""Enqueue + parse job-extract SQS messages (plan §14 Phase 4).

Two entrypoints:

* :func:`enqueue_unextracted_for_account` — called after classification
  lands so every ``job_candidate`` email that lacks a
  :class:`app.db.models.JobMatch` row gets one enqueued message.
* :func:`parse_job_extract_body` — validates a raw SQS body into a
  :class:`app.workers.messages.JobExtractMessage`. Mirrors
  :func:`app.services.classification.dispatch.parse_classify_body`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import Classification, Email, JobMatch
from app.workers.messages import JobExtractMessage

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger(__name__)

_JOB_LABEL = "job_candidate"
"""Classification label that qualifies for job extraction."""


class SqsSender(Protocol):
    """Subset of boto3 SQS we rely on."""

    def send_message(
        self,
        *,
        QueueUrl: str,
        MessageBody: str,
    ) -> dict[str, Any]:
        """Enqueue one SQS message."""


async def enqueue_unextracted_for_account(
    *,
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    queue_url: str,
    sqs: SqsSender,
    run_id: UUID | None,
    prompt_name: str = "job_extract",
    prompt_version: int = 1,
    limit: int = 200,
) -> int:
    """Enqueue one :class:`JobExtractMessage` per un-extracted job_candidate.

    Args:
        session: Active async session.
        user_id: Owner.
        account_id: Connected account.
        queue_url: Destination SQS URL.
        sqs: boto3-compatible SQS client.
        run_id: Optional digest-run id.
        prompt_name: Prompt key to carry on the payload.
        prompt_version: Prompt version to carry.
        limit: Cap per call — job candidates are a minority of traffic
            so 200 per account per run is plenty.

    Returns:
        Count of messages enqueued.
    """
    stmt = (
        select(Email.id)
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(JobMatch, JobMatch.email_id == Email.id)
        .where(
            Email.account_id == account_id,
            Classification.label == _JOB_LABEL,
            JobMatch.email_id.is_(None),
        )
        .order_by(Email.internal_date.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()

    enqueued = 0
    for email_id in rows:
        message = JobExtractMessage(
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
        "jobs.dispatch.enqueued",
        account_id=str(account_id),
        run_id=str(run_id) if run_id else None,
        enqueued=enqueued,
    )
    return enqueued


def parse_job_extract_body(body: str) -> JobExtractMessage:
    """Validate + parse a raw SQS body into :class:`JobExtractMessage`.

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
    return JobExtractMessage.model_validate(payload)


__all__ = [
    "SqsSender",
    "enqueue_unextracted_for_account",
    "parse_job_extract_body",
]
