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

    Phase 0: stub — logs each record and reports success. Phases 1+ add
    real routing based on the source queue name (ingest / classify /
    summarize / jobs / unsubscribe / digest / maintenance).

    Args:
        event: SQS event envelope from Lambda; see AWS docs.
        _context: Lambda runtime context. Unused in the stub.

    Returns:
        A partial-batch-response with an empty failure list (all records
        acknowledged). When real handlers fail, records that couldn't be
        processed are appended to ``batchItemFailures``.
    """
    records = event.get("Records", [])
    for record in records:
        logger.info(
            "sqs_dispatcher.record",
            message_id=record.get("messageId", "<no-id>"),
            source=record.get("eventSourceARN", "<unknown>"),
        )

    return {"batchItemFailures": []}


def fanout_handler(_event: dict[str, Any], _context: Any) -> dict[str, int]:
    """Enqueue one ingestion job per connected account for the daily cron.

    Phase 0: stub — returns a zero-count payload. Phase 1 replaces this
    with a query against ``connected_accounts`` + ``sqs.send_message_batch``
    to the ``ingest`` queue.

    Args:
        _event: EventBridge Scheduler event payload. Unused in the stub.
        _context: Lambda runtime context. Unused in the stub.

    Returns:
        A mapping with an ``accounts_enqueued`` counter, useful for
        CloudWatch metric filters.
    """
    logger.info("fanout_handler.invoked", accounts_enqueued=0)
    return {"accounts_enqueued": 0}
