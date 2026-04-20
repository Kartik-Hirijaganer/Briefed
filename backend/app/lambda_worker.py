"""AWS Lambda worker entrypoints (plan §19.15).

Two handlers share this module so we only ship one container image:

* :func:`sqs_dispatcher` — consumes an SQS batch, routes each record to
  the stage-specific worker handler based on the source queue ARN.
* :func:`fanout_handler` — invoked by EventBridge Scheduler; enumerates
  connected accounts and enqueues one ingestion job per account onto the
  ``ingest`` queue.

Phase 0 ships stubs only; Phases 1+ fill in per-stage logic under
``app.workers.handlers``. The handlers intentionally avoid any import
that isn't strictly necessary so Lambda SnapStart's cold snapshot stays
small.
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.core.config import get_settings
from app.core.logging import configure as configure_logging
from app.core.logging import get_logger

# SnapStart-friendly module init: load settings (SSM hydration happens
# here on cold start) + configure logging before any handler runs. Both
# calls are idempotent — repeated imports during tests are cheap.
_settings = get_settings()
configure_logging(level=_settings.log_level, json_output=_settings.runtime != "local")

logger = get_logger(__name__)


class _SqsRecord(TypedDict, total=False):
    """Minimal shape of an SQS event record we rely on.

    Boto / AWS send many more fields; we only consume what we need and
    ignore the rest to stay forward-compatible.
    """

    eventSourceARN: str
    messageId: str
    body: str


class _SqsEvent(TypedDict):
    """Minimal shape of the SQS Lambda event envelope."""

    Records: list[_SqsRecord]


class _BatchItemFailure(TypedDict):
    """Partial-batch-response entry per AWS contract."""

    itemIdentifier: str


class _PartialBatchResponse(TypedDict):
    """Return shape when ``function_response_types = ["ReportBatchItemFailures"]``."""

    batchItemFailures: list[_BatchItemFailure]


def sqs_dispatcher(event: _SqsEvent, _context: Any) -> _PartialBatchResponse:
    """Dispatch an SQS batch to the appropriate per-stage handler.

    Routing keys off the tail segment of ``eventSourceARN`` so one
    Lambda can back every queue. Phase 1 wires ``ingest`` to
    :func:`app.workers.handlers.ingest.handle_ingest`; later phases add
    classify / summarize / jobs / unsubscribe / digest / maintenance.

    Args:
        event: SQS event envelope from Lambda; see AWS docs.
        _context: Lambda runtime context. Unused.

    Returns:
        A partial-batch-response listing records that failed and should
        be re-delivered. Succesful records are acked implicitly.
    """
    import asyncio

    records = event.get("Records", [])
    failures: list[_BatchItemFailure] = []
    if not records:
        return {"batchItemFailures": failures}

    async def _dispatch() -> None:
        for record in records:
            message_id = record.get("messageId", "<no-id>")
            source = record.get("eventSourceARN", "<unknown>")
            stage = source.rsplit("-", 1)[-1]
            try:
                if stage == "ingest":
                    await _handle_ingest_record(record)
                else:
                    logger.warning(
                        "sqs_dispatcher.unknown_stage",
                        stage=stage,
                        message_id=message_id,
                    )
            except Exception as exc:
                logger.exception(
                    "sqs_dispatcher.failure",
                    message_id=message_id,
                    stage=stage,
                    error=str(exc),
                )
                failures.append({"itemIdentifier": message_id})

    asyncio.run(_dispatch())
    return {"batchItemFailures": failures}


async def _handle_ingest_record(record: _SqsRecord) -> None:
    """Decode + dispatch one ingest-queue record.

    Args:
        record: Raw SQS record from the event envelope.
    """
    import os

    import boto3  # type: ignore[import-untyped]
    import httpx

    from app.core.security import EnvelopeCipher
    from app.db.session import get_sessionmaker
    from app.services.gmail.client import GmailClient
    from app.services.gmail.provider import GmailProvider
    from app.workers.handlers.fanout import parse_ingest_body
    from app.workers.handlers.ingest import IngestDeps, handle_ingest

    message = parse_ingest_body(record.get("body", "{}"))
    alias = os.environ.get("BRIEFED_TOKEN_WRAP_KEY_ALIAS", "")
    if not alias:
        raise RuntimeError("BRIEFED_TOKEN_WRAP_KEY_ALIAS unset")

    async with httpx.AsyncClient() as http:
        provider = GmailProvider(
            client=GmailClient(http_client=http),
            http_client=http,
        )
        async with get_sessionmaker()() as session:
            deps = IngestDeps(
                session=session,
                provider=provider,
                cipher=EnvelopeCipher(key_id=alias, client=boto3.client("kms")),
            )
            await handle_ingest(message, deps=deps)
            await session.commit()


def fanout_handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    """Enqueue one ingestion job per active connected account.

    Wires the scheduler event into :func:`app.workers.handlers.fanout.run_fanout`.
    The actual SQS send + DB query live in that handler so tests can
    exercise the logic without a Lambda harness.

    Args:
        event: EventBridge Scheduler event payload. A ``user_id`` field,
            when present, restricts the fan-out to a single owner.
        _context: Lambda runtime context. Unused.

    Returns:
        A mapping with an ``accounts_enqueued`` counter, useful for
        CloudWatch metric filters.
    """
    import asyncio
    import os

    import boto3

    from app.db.session import get_sessionmaker
    from app.workers.handlers.fanout import FanoutDeps, run_fanout

    queue_url = os.environ.get("BRIEFED_INGEST_QUEUE_URL", "")
    if not queue_url:
        logger.error("fanout_handler.missing_queue_url")
        return {"accounts_enqueued": 0}

    raw_user = event.get("user_id") if isinstance(event, dict) else None
    user_filter = None
    if isinstance(raw_user, str):
        from uuid import UUID

        try:
            user_filter = UUID(raw_user)
        except ValueError:
            logger.warning("fanout_handler.bad_user_id", value=raw_user)

    async def _run() -> int:
        async with get_sessionmaker()() as session:
            deps = FanoutDeps(
                session=session,
                sqs=boto3.client("sqs"),
                ingest_queue_url=queue_url,
                store_raw_mime=os.environ.get("BRIEFED_STORE_RAW_MIME", "0") == "1",
            )
            return await run_fanout(deps=deps, user_id=user_filter)

    enqueued = asyncio.run(_run())
    logger.info("fanout_handler.completed", accounts_enqueued=enqueued)
    return {"accounts_enqueued": enqueued}
