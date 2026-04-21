"""Enqueue + parse summarize-queue SQS messages (plan §14 Phase 3).

Two entrypoints:

* :func:`enqueue_unsummarized_for_run` — called from the classify /
  worker edge after a run's classifications land. Selects classified
  rows that still lack a :class:`app.db.models.Summary` and enqueues one
  :class:`SummarizeEmailMessage` per must-read / good-to-read / newsletter
  email, plus one aggregate :class:`TechNewsClusterMessage` for the run.
* :func:`parse_summarize_body` — validates a raw SQS body into the
  right Pydantic payload. Mirrors
  :func:`app.services.classification.dispatch.parse_classify_body`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import Classification, Email, Summary
from app.workers.messages import (
    SummarizeEmailMessage,
    TechNewsClusterMessage,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger(__name__)

_SUMMARIZABLE_LABELS: tuple[str, ...] = (
    "must_read",
    "good_to_read",
    "newsletter",
)
"""Classification labels that qualify for a per-email summary."""

_NEWSLETTER_LABEL = "newsletter"


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


async def enqueue_unsummarized_for_run(
    *,
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    queue_url: str,
    sqs: SqsSender,
    run_id: UUID | None,
    prompt_name: str = "summarize_relevant",
    prompt_version: int = 1,
    cluster_prompt_name: str = "newsletter_group",
    cluster_prompt_version: int = 1,
    limit: int = 500,
) -> tuple[int, int]:
    """Enqueue summarize messages for a (user, account) scope.

    Args:
        session: Active async session.
        user_id: Owner.
        account_id: Connected account.
        queue_url: Destination SQS URL.
        sqs: boto3-compatible SQS client.
        run_id: Optional digest-run id.
        prompt_name: Per-email prompt key.
        prompt_version: Per-email prompt version.
        cluster_prompt_name: Cluster prompt key.
        cluster_prompt_version: Cluster prompt version.
        limit: Cap on per-email enqueues.

    Returns:
        Tuple ``(per_email_count, cluster_count)`` — ``cluster_count``
        is 0 or 1.
    """
    stmt = (
        select(Email.id, Classification.label)
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(Summary, Summary.email_id == Email.id)
        .where(
            Email.account_id == account_id,
            Classification.label.in_(_SUMMARIZABLE_LABELS),
            Summary.email_id.is_(None),
        )
        .order_by(Email.internal_date.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    per_email = 0
    newsletter_ids: list[UUID] = []
    for email_id, label in rows:
        msg = SummarizeEmailMessage(
            user_id=user_id,
            account_id=account_id,
            email_id=email_id,
            run_id=run_id,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
        )
        sqs.send_message(QueueUrl=queue_url, MessageBody=msg.model_dump_json())
        per_email += 1
        if label == _NEWSLETTER_LABEL:
            newsletter_ids.append(email_id)

    cluster_count = 0
    if len(newsletter_ids) >= 2:
        cluster_msg = TechNewsClusterMessage(
            user_id=user_id,
            run_id=run_id,
            email_ids=tuple(newsletter_ids),
            prompt_name=cluster_prompt_name,
            prompt_version=cluster_prompt_version,
        )
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=cluster_msg.model_dump_json(),
        )
        cluster_count = 1

    logger.info(
        "summarize.dispatch.enqueued",
        account_id=str(account_id),
        run_id=str(run_id) if run_id else None,
        per_email=per_email,
        cluster=cluster_count,
    )
    return per_email, cluster_count


async def enqueue_summary_for_email(
    *,
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    email_id: UUID,
    queue_url: str,
    sqs: SqsSender,
    run_id: UUID | None,
    prompt_name: str = "summarize_relevant",
    prompt_version: int = 1,
) -> int:
    """Enqueue one summary message if the just-classified email qualifies.

    This is the Lambda hot path after a single classify record. It keeps
    retries idempotent by requiring the source email to lack a summary
    row at enqueue time.
    """
    stmt = (
        select(Email.id)
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(Summary, Summary.email_id == Email.id)
        .where(
            Email.id == email_id,
            Email.account_id == account_id,
            Classification.label.in_(_SUMMARIZABLE_LABELS),
            Summary.email_id.is_(None),
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return 0

    message = SummarizeEmailMessage(
        user_id=user_id,
        account_id=account_id,
        email_id=email_id,
        run_id=run_id,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
    )
    sqs.send_message(QueueUrl=queue_url, MessageBody=message.model_dump_json())
    logger.info(
        "summarize.dispatch.enqueued_email",
        account_id=str(account_id),
        email_id=str(email_id),
        run_id=str(run_id) if run_id else None,
    )
    return 1


def parse_summarize_body(
    body: str,
) -> SummarizeEmailMessage | TechNewsClusterMessage:
    """Validate + parse a raw SQS summarize-queue body.

    Args:
        body: Raw JSON body string from the SQS event record.

    Returns:
        Validated :class:`SummarizeEmailMessage` or
        :class:`TechNewsClusterMessage`.

    Raises:
        ValueError: When the JSON is malformed or the discriminator is
            missing / unknown.
    """
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("summarize body must be a JSON object")
    kind = payload.get("kind")
    if kind == "summarize_email":
        return SummarizeEmailMessage.model_validate(payload)
    if kind == "tech_news_cluster":
        return TechNewsClusterMessage.model_validate(payload)
    raise ValueError(f"unknown summarize message kind: {kind!r}")


__all__ = [
    "SqsSender",
    "enqueue_summary_for_email",
    "enqueue_unsummarized_for_run",
    "parse_summarize_body",
]
