"""Enqueue + parse summarize-queue SQS messages (plan §14 Phase 3).

Two entrypoints:

* :func:`enqueue_unsummarized_for_run` — called from the classify /
  worker edge after a run's classifications land. Selects classified
  rows that still lack a :class:`app.db.models.Summary` and enqueues one
  :class:`SummarizeEmailMessage` per must-read / good-to-read / newsletter
  email, plus one aggregate :class:`TechNewsClusterMessage` for classified
  newsletters in the run/account scope.
* :func:`parse_summarize_body` — validates a raw SQS body into the
  right Pydantic payload. Mirrors
  :func:`app.services.classification.dispatch.parse_classify_body`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy import or_, select

from app.core.app_config import get_app_config
from app.core.logging import get_logger
from app.db.models import Classification, DigestRunEmail, Email, Summary, TechNewsCluster
from app.services.email_labels import unread_email_filter
from app.workers.messages import (
    CategoryDigestMessage,
    SummarizeEmailMessage,
    TechNewsClusterMessage,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger(__name__)
_APP_CONFIG = get_app_config()

_SUMMARIZABLE_LABELS: tuple[str, ...] = _APP_CONFIG.taxonomy.summarizable_labels
"""Primary labels and legacy pseudo-labels that qualify for a summary."""

_NEWSLETTER_LABEL = _APP_CONFIG.taxonomy.newsletter_label
_NEWSLETTER_CLUSTERING_ENABLED = _APP_CONFIG.features.newsletter_clustering


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
        select(Email.id)
        .join(Classification, Classification.email_id == Email.id)
        .outerjoin(Summary, Summary.email_id == Email.id)
        .where(
            Email.account_id == account_id,
            unread_email_filter(session),
            or_(
                Classification.label.in_(_SUMMARIZABLE_LABELS),
                Classification.is_newsletter.is_(True),
            ),
            Summary.email_id.is_(None),
        )
        .order_by(Email.internal_date.desc())
        .limit(limit)
    )
    if run_id is not None:
        stmt = stmt.join(DigestRunEmail, DigestRunEmail.email_id == Email.id).where(
            DigestRunEmail.run_id == run_id,
        )
    rows = (await session.execute(stmt)).scalars().all()

    per_email = 0
    for email_id in rows:
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

    cluster_count = await enqueue_tech_news_cluster_for_account(
        session=session,
        user_id=user_id,
        account_id=account_id,
        queue_url=queue_url,
        sqs=sqs,
        run_id=run_id,
        prompt_name=cluster_prompt_name,
        prompt_version=cluster_prompt_version,
        limit=limit,
    )

    logger.info(
        "summarize.dispatch.enqueued",
        account_id=str(account_id),
        run_id=str(run_id) if run_id else None,
        per_email=per_email,
        cluster=cluster_count,
    )
    return per_email, cluster_count


async def enqueue_tech_news_cluster_for_account(
    *,
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    queue_url: str,
    sqs: SqsSender,
    run_id: UUID | None,
    prompt_name: str = "newsletter_group",
    prompt_version: int = 1,
    trigger_email_id: UUID | None = None,
    limit: int = 500,
) -> int:
    """Enqueue one tech-news cluster message for newsletter rows.

    Args:
        session: Active async session.
        user_id: Owner.
        account_id: Connected account whose classified newsletters are scanned.
        queue_url: Destination SQS URL.
        sqs: boto3-compatible SQS client.
        run_id: Optional digest-run id.
        prompt_name: Cluster prompt key.
        prompt_version: Cluster prompt version.
        trigger_email_id: Optional just-classified email id. When present,
            the helper only enqueues if that email is a newsletter.
        limit: Cap on newsletter ids included in the aggregate message.

    Returns:
        ``1`` when a cluster message was enqueued, otherwise ``0``.
    """
    if not _NEWSLETTER_CLUSTERING_ENABLED:
        return 0

    existing_stmt = (
        select(Summary.id)
        .join(TechNewsCluster, Summary.cluster_id == TechNewsCluster.id)
        .where(
            TechNewsCluster.user_id == user_id,
            Summary.kind == "tech_news_cluster",
        )
        .limit(1)
    )
    if run_id is None:
        existing_stmt = existing_stmt.where(TechNewsCluster.run_id.is_(None))
    else:
        existing_stmt = existing_stmt.where(TechNewsCluster.run_id == run_id)
    if (await session.execute(existing_stmt)).scalar_one_or_none() is not None:
        return 0

    stmt = (
        select(Email.id)
        .join(Classification, Classification.email_id == Email.id)
        .where(
            Email.account_id == account_id,
            unread_email_filter(session),
            or_(
                Classification.label == _NEWSLETTER_LABEL,
                Classification.is_newsletter.is_(True),
            ),
        )
        .order_by(Email.internal_date.desc())
        .limit(limit)
    )
    if run_id is not None:
        stmt = stmt.join(DigestRunEmail, DigestRunEmail.email_id == Email.id).where(
            DigestRunEmail.run_id == run_id,
        )
    newsletter_ids = list((await session.execute(stmt)).scalars().all())
    if len(newsletter_ids) < 2:
        return 0
    if trigger_email_id is not None and trigger_email_id not in newsletter_ids:
        return 0

    cluster_msg = TechNewsClusterMessage(
        user_id=user_id,
        run_id=run_id,
        email_ids=tuple(newsletter_ids),
        prompt_name=prompt_name,
        prompt_version=prompt_version,
    )
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=cluster_msg.model_dump_json(),
    )
    logger.info(
        "summarize.dispatch.enqueued_tech_news_cluster",
        account_id=str(account_id),
        run_id=str(run_id) if run_id else None,
        newsletters=len(newsletter_ids),
    )
    return 1


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
            unread_email_filter(session),
            or_(
                Classification.label.in_(_SUMMARIZABLE_LABELS),
                Classification.is_newsletter.is_(True),
            ),
            Summary.email_id.is_(None),
        )
        .limit(1)
    )
    if run_id is not None:
        stmt = stmt.join(DigestRunEmail, DigestRunEmail.email_id == Email.id).where(
            DigestRunEmail.run_id == run_id,
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
) -> SummarizeEmailMessage | TechNewsClusterMessage | CategoryDigestMessage:
    """Validate + parse a raw SQS summarize-queue body.

    Args:
        body: Raw JSON body string from the SQS event record.

    Returns:
        Validated summarize-queue message payload.

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
    if kind == "category_digest":
        return CategoryDigestMessage.model_validate(payload)
    raise ValueError(f"unknown summarize message kind: {kind!r}")


__all__ = [
    "SqsSender",
    "enqueue_summary_for_email",
    "enqueue_tech_news_cluster_for_account",
    "enqueue_unsummarized_for_run",
    "parse_summarize_body",
]
