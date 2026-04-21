"""Fan-out Lambda handler (plan §19.15).

EventBridge Scheduler fires once per user cron, invoking this handler.
It enumerates active connected accounts (optionally filtered by
``user_id``) and enqueues one :class:`IngestMessage` onto the ingest
queue for each.

Kept pure-ish: the real SQS + DB clients are injected via
:class:`FanoutDeps` so tests drive the logic without AWS/DB.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy import select

from app.core.ids import new_uuid
from app.core.logging import get_logger
from app.db.models import ConnectedAccount
from app.workers.messages import IngestMessage

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger(__name__)


class SqsSender(Protocol):
    """Structural typing for the subset of boto3 SQS used by fan-out."""

    def send_message(
        self,
        *,
        QueueUrl: str,
        MessageBody: str,
    ) -> dict[str, Any]:
        """Enqueue one message onto ``QueueUrl``."""
        ...


@dataclass
class FanoutDeps:
    """Collaborators the fan-out handler needs.

    Attributes:
        session: Open :class:`AsyncSession` for reads.
        sqs: SQS client used for :meth:`send_message` calls.
        ingest_queue_url: Full queue URL for the ingest queue.
        store_raw_mime: Whether newly-enqueued messages should opt in to
            raw-MIME storage (owner-level preference — Phase 1 uses a
            single global flag until :mod:`preferences` ships in Phase 6).
    """

    session: AsyncSession
    sqs: SqsSender
    ingest_queue_url: str
    store_raw_mime: bool = False


async def run_fanout(
    *,
    deps: FanoutDeps,
    user_id: UUID | None = None,
) -> int:
    """Enumerate active accounts and enqueue one ingest job each.

    Args:
        deps: :class:`FanoutDeps` with DB + SQS collaborators.
        user_id: Optional user filter. When ``None`` the fan-out selects
            every active account across the system.

    Returns:
        Count of accounts actually enqueued.
    """
    stmt = select(ConnectedAccount).where(
        ConnectedAccount.status == "active",
        ConnectedAccount.auto_scan_enabled.is_(True),
    )
    if user_id is not None:
        stmt = stmt.where(ConnectedAccount.user_id == user_id)

    accounts = (await deps.session.execute(stmt)).scalars().all()
    run_id = new_uuid()
    enqueued = 0
    for account in accounts:
        message = IngestMessage(
            user_id=account.user_id,
            account_id=account.id,
            run_id=run_id,
            store_raw_mime=deps.store_raw_mime,
        )
        deps.sqs.send_message(
            QueueUrl=deps.ingest_queue_url,
            MessageBody=message.model_dump_json(),
        )
        enqueued += 1

    logger.info(
        "fanout.completed",
        run_id=str(run_id),
        enqueued=enqueued,
        user_filter=str(user_id) if user_id else None,
    )
    return enqueued


def parse_ingest_body(body: str) -> IngestMessage:
    """Parse the raw SQS body string into :class:`IngestMessage`.

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
    return IngestMessage.model_validate(payload)
