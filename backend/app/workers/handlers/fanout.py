"""Fan-out Lambda handler (plan §19.15 + Track C — Phase II.4).

EventBridge Scheduler fires every 15 minutes UTC. The handler:

1. Enumerates users whose schedule could plausibly be due (cheap SQL
   filter). The Python-side :func:`app.core.scheduling.is_due` then
   re-checks each row authoritatively — branching the predicate would
   let the UI lie about when the next run will land.
2. Acquires the per-user idempotency lock (``current_run_id`` +
   ``current_run_started_at``) before enqueueing. A second tick that
   arrives before the lock clears (success or 30-min stale-lock
   window) skips the user.
3. Enqueues one :class:`IngestMessage` per active connected account
   for the lucky users.

Kept pure-ish: the real SQS + DB clients are injected via
:class:`FanoutDeps` so tests drive the logic without AWS/DB.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.ids import new_uuid
from app.core.logging import get_logger
from app.core.scheduling import UserScheduleView, is_due
from app.db.models import ConnectedAccount, User
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


def _schedule_view(user: User) -> UserScheduleView:
    """Project a ``users`` row into the predicate's view."""
    return UserScheduleView(
        schedule_frequency=user.schedule_frequency,
        schedule_times_local=tuple(user.schedule_times_local or ()),
        schedule_timezone=user.schedule_timezone,
        last_run_finished_at=user.last_run_finished_at,
        current_run_id=user.current_run_id,
        current_run_started_at=user.current_run_started_at,
    )


async def run_fanout(
    *,
    deps: FanoutDeps,
    user_id: UUID | None = None,
) -> int:
    """Enumerate due users and enqueue one ingest job per account.

    SQL pre-filter is intentionally narrow (``schedule_frequency !=
    'disabled'``); the authoritative check is :func:`is_due` in Python
    so cross-tz, DST, and stale-lock semantics live in one place.

    On enqueue the per-user idempotency lock is set
    (``current_run_id`` = the freshly-minted run UUID,
    ``current_run_started_at`` = ``utcnow()``). The lock clears on
    final-stage completion (see :func:`release_user_lock`) or after
    :data:`app.core.scheduling.LOCK_STALE_AFTER` minutes if a worker
    crashes before it can clear the lock.

    Args:
        deps: :class:`FanoutDeps` with DB + SQS collaborators.
        user_id: Optional user filter. When ``None`` every user is
            considered.

    Returns:
        Count of accounts actually enqueued across all due users.
    """
    user_stmt = select(User).where(
        User.status == "active",
        User.schedule_frequency != "disabled",
    )
    if user_id is not None:
        user_stmt = user_stmt.where(User.id == user_id)
    users = (await deps.session.execute(user_stmt)).scalars().all()

    now_utc = utcnow()
    enqueued = 0
    skipped_disabled = 0
    skipped_locked = 0
    for user in users:
        if not is_due(now_utc, _schedule_view(user)):
            skipped_disabled += 1
            continue

        account_stmt = select(ConnectedAccount).where(
            ConnectedAccount.user_id == user.id,
            ConnectedAccount.status == "active",
            ConnectedAccount.auto_scan_enabled.is_(True),
        )
        accounts = (await deps.session.execute(account_stmt)).scalars().all()
        if not accounts:
            continue

        run_id = new_uuid()
        # Acquire the idempotency lock before enqueueing. A second tick
        # that lands while messages are still in flight will fail the
        # is_due check and skip — see app.core.scheduling docstring.
        user.current_run_id = str(run_id)
        user.current_run_started_at = now_utc
        await deps.session.flush()

        for account in accounts:
            message = IngestMessage(
                user_id=user.id,
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
        enqueued=enqueued,
        skipped_disabled=skipped_disabled,
        skipped_locked=skipped_locked,
        user_filter=str(user_id) if user_id else None,
    )
    return enqueued


async def release_user_lock(
    *,
    session: AsyncSession,
    user_id: UUID,
    run_id: UUID,
) -> None:
    """Clear the user's idempotency lock on final-stage completion.

    Workers MUST call this once the last per-email piece of work for
    ``run_id`` lands — without it the next 15-min tick would be
    suppressed by the freshness debounce until the 30-min stale-lock
    window releases it.

    Args:
        session: Open DB session.
        user_id: User whose lock should be cleared.
        run_id: Active ``current_run_id`` to clear. Mismatched run ids
            are ignored — a stale worker must not clobber a fresher run.
    """
    user = await session.get(User, user_id)
    if user is None:
        return
    if user.current_run_id != str(run_id):
        return
    user.current_run_id = None
    user.current_run_started_at = None
    user.last_run_finished_at = utcnow()
    await session.flush()


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
