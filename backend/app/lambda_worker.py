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

from typing import TYPE_CHECKING, Any, TypedDict, cast

from app.core.config import get_settings
from app.core.logging import configure as configure_logging
from app.core.logging import get_logger
from app.core.sentry import configure_sentry
from app.core.tracing import configure_tracing

# SnapStart-friendly module init: load settings (SSM hydration happens
# here on cold start) + configure logging + tracing + sentry before any
# handler runs. All four calls are idempotent — repeated imports during
# tests are cheap, and SnapStart restores skip the work entirely.
_settings = get_settings()
configure_tracing(_settings)
configure_logging(level=_settings.log_level, json_output=_settings.runtime != "local")
configure_sentry(_settings)

logger = get_logger(__name__)


if TYPE_CHECKING:  # pragma: no cover
    from app.core.security import KmsClient
    from app.services.classification.dispatch import SqsSender
    from app.services.ingestion.storage import ObjectStore


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


def _build_redaction_chain() -> Any:
    """Construct the Track B sanitizer chain from settings.

    Returns:
        A :class:`app.llm.redaction.SanitizerChain`. Identity scrubber
        only fires when the user-identifying envs are populated; until
        Track C ships, those come from
        ``BRIEFED_USER_EMAIL`` / ``BRIEFED_USER_NAME`` /
        ``BRIEFED_USER_ALIASES``.
    """
    from app.llm.redaction import build_default_chain

    aliases_csv = (_settings.user_aliases or "").strip()
    aliases = tuple(alias.strip() for alias in aliases_csv.split(",") if alias.strip())
    return build_default_chain(
        user_email=_settings.user_email,
        user_name=_settings.user_name,
        aliases=aliases,
        presidio_enabled=_settings.redaction_presidio_enabled,
    )


def _kms_client() -> KmsClient:
    """Return a boto3 KMS client narrowed to the protocol this module needs."""
    import boto3  # type: ignore[import-untyped]

    return cast("KmsClient", boto3.client("kms"))


def _sqs_client() -> SqsSender:
    """Return a boto3 SQS client narrowed to the protocol this module needs."""
    import boto3

    return cast("SqsSender", boto3.client("sqs"))


def _s3_client() -> ObjectStore:
    """Return a boto3 S3 client narrowed to the storage protocol."""
    import boto3

    return cast("ObjectStore", boto3.client("s3"))


def sqs_dispatcher(event: _SqsEvent, _context: Any) -> _PartialBatchResponse:
    """Dispatch an SQS batch to the appropriate per-stage handler.

    Routing keys off the tail segment of ``eventSourceARN`` so one
    Lambda can back every queue. Phases 1-5 wire ``ingest`` to
    :func:`app.workers.handlers.ingest.handle_ingest`, ``classify`` to
    :func:`app.workers.handlers.classify.handle_classify`, ``summarize``
    to :mod:`app.workers.handlers.summarize`, ``jobs`` to
    :func:`app.workers.handlers.jobs.handle_job_extract`, and
    ``unsubscribe`` to
    :func:`app.workers.handlers.unsubscribe.handle_unsubscribe`. Later
    phases add ``digest`` / ``maintenance``.

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

    from app.core.tracing import worker_span

    async def _dispatch() -> None:
        for record in records:
            message_id = record.get("messageId", "<no-id>")
            source = record.get("eventSourceARN", "<unknown>")
            stage = source.rsplit("-", 1)[-1]
            try:
                with worker_span(
                    f"worker.{stage}",
                    message_id=message_id,
                    stage=stage,
                ):
                    if stage == "ingest":
                        await _handle_ingest_record(record)
                    elif stage == "classify":
                        await _handle_classify_record(record)
                    elif stage == "summarize":
                        await _handle_summarize_record(record)
                    elif stage == "jobs":
                        await _handle_jobs_record(record)
                    elif stage == "unsubscribe":
                        await _handle_unsubscribe_record(record)
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

    import httpx

    from app.core.security import EnvelopeCipher
    from app.db.session import get_sessionmaker
    from app.services.classification.dispatch import enqueue_unclassified_for_account
    from app.services.gmail.client import GmailClient
    from app.services.gmail.provider import GmailProvider
    from app.workers.handlers.fanout import parse_ingest_body
    from app.workers.handlers.ingest import IngestDeps, handle_ingest

    message = parse_ingest_body(record.get("body", "{}"))
    alias = os.environ.get("BRIEFED_TOKEN_WRAP_KEY_ALIAS", "")
    if not alias:
        raise RuntimeError("BRIEFED_TOKEN_WRAP_KEY_ALIAS unset")
    content_alias = os.environ.get("BRIEFED_CONTENT_KEY_ALIAS", "")
    if not content_alias:
        raise RuntimeError("BRIEFED_CONTENT_KEY_ALIAS unset")

    classify_queue_url = os.environ.get("BRIEFED_CLASSIFY_QUEUE_URL", "")
    raw_bucket = os.environ.get("BRIEFED_RAW_EMAIL_BUCKET", "")
    if message.store_raw_mime and not raw_bucket:
        raise RuntimeError("BRIEFED_RAW_EMAIL_BUCKET unset while raw MIME storage is enabled")

    async with httpx.AsyncClient() as http:
        provider = GmailProvider(
            client=GmailClient(http_client=http),
            http_client=http,
        )
        async with get_sessionmaker()() as session:
            deps = IngestDeps(
                session=session,
                provider=provider,
                cipher=EnvelopeCipher(key_id=alias, client=_kms_client()),
                content_cipher=EnvelopeCipher(key_id=content_alias, client=_kms_client()),
                raw_storage=_s3_client() if message.store_raw_mime else None,
                raw_bucket=raw_bucket or None,
                oauth_client_id=_settings.google_oauth_client_id,
                oauth_client_secret=_settings.google_oauth_client_secret,
                http_client=http,
            )
            stats = await handle_ingest(message, deps=deps)
            if stats.new and classify_queue_url:
                sqs = _sqs_client()
                await enqueue_unclassified_for_account(
                    session=session,
                    user_id=message.user_id,
                    account_id=message.account_id,
                    queue_url=classify_queue_url,
                    sqs=sqs,
                    run_id=message.run_id,
                )
            await session.commit()


async def _handle_classify_record(record: _SqsRecord) -> None:
    """Decode + dispatch one classify-queue record (plan §14 Phase 2).

    After the classification lands, enqueue only this email's eligible
    downstream work. The dispatch helpers require the target row to
    still lack a summary/job-match row, so SQS retries do not rescan the
    whole account or fan out duplicate LLM work.

    Args:
        record: Raw SQS record from the event envelope.
    """
    import os

    import httpx

    from app.core.security import EnvelopeCipher
    from app.db.session import get_sessionmaker
    from app.llm.factory import build_llm_client
    from app.services.classification.dispatch import parse_classify_body
    from app.services.classification.repository import ClassificationsRepo
    from app.services.jobs.dispatch import enqueue_job_extract_for_email
    from app.services.prompts.registry import PromptRegistry
    from app.services.summarization import enqueue_summary_for_email
    from app.services.unsubscribe.dispatch import enqueue_hygiene_run_for_account
    from app.workers.handlers.classify import ClassifyDeps, handle_classify

    message = parse_classify_body(record.get("body", "{}"))
    content_alias = os.environ.get("BRIEFED_CONTENT_KEY_ALIAS", "")
    if not content_alias:
        raise RuntimeError("BRIEFED_CONTENT_KEY_ALIAS unset")
    summarize_queue_url = os.environ.get("BRIEFED_SUMMARIZE_QUEUE_URL", "")
    jobs_queue_url = os.environ.get("BRIEFED_JOBS_QUEUE_URL", "")
    unsubscribe_queue_url = os.environ.get("BRIEFED_UNSUBSCRIBE_QUEUE_URL", "")

    async with httpx.AsyncClient() as http:
        llm = build_llm_client(
            settings=_settings,
            http_client=http,
            sanitizer=_build_redaction_chain(),
        )
        cipher = EnvelopeCipher(key_id=content_alias, client=_kms_client())
        async with get_sessionmaker()() as session:
            registry = PromptRegistry.load()
            await registry.sync_to_db(session)
            deps = ClassifyDeps(
                session=session,
                llm=llm,
                registry=registry,
                repo=ClassificationsRepo(cipher=cipher),
                content_cipher=cipher,
            )
            await handle_classify(message, deps=deps)
            sqs_client = _sqs_client()
            if summarize_queue_url:
                await enqueue_summary_for_email(
                    session=session,
                    user_id=message.user_id,
                    account_id=message.account_id,
                    email_id=message.email_id,
                    queue_url=summarize_queue_url,
                    sqs=sqs_client,
                    run_id=message.run_id,
                )
            if jobs_queue_url:
                await enqueue_job_extract_for_email(
                    session=session,
                    user_id=message.user_id,
                    account_id=message.account_id,
                    email_id=message.email_id,
                    queue_url=jobs_queue_url,
                    sqs=sqs_client,
                    run_id=message.run_id,
                )
            if unsubscribe_queue_url:
                # The hygiene aggregate runs over the trailing 30 days,
                # so enqueueing once per classify record produces
                # duplicate messages — cheap and idempotent (each run
                # re-sweeps the same window and upserts rows while
                # preserving ``dismissed`` state). A future
                # optimization can debounce to one message per
                # (account, run) when a run-scoped ledger lands.
                await enqueue_hygiene_run_for_account(
                    user_id=message.user_id,
                    account_id=message.account_id,
                    queue_url=unsubscribe_queue_url,
                    sqs=sqs_client,
                    run_id=message.run_id,
                )
            await session.commit()


async def _handle_summarize_record(record: _SqsRecord) -> None:
    """Decode + dispatch one summarize-queue record (plan §14 Phase 3).

    Routes to :func:`app.workers.handlers.summarize.handle_summarize_email`
    or :func:`.handle_tech_news_cluster` based on the message kind.

    Args:
        record: Raw SQS record from the event envelope.
    """
    import os

    import httpx

    from app.core.security import EnvelopeCipher
    from app.db.session import get_sessionmaker
    from app.llm.factory import build_llm_client
    from app.services.prompts.registry import PromptRegistry
    from app.services.summarization import SummariesRepo, parse_summarize_body
    from app.workers.handlers.summarize import (
        SummarizeDeps,
        handle_summarize_email,
        handle_tech_news_cluster,
    )
    from app.workers.messages import SummarizeEmailMessage

    message = parse_summarize_body(record.get("body", "{}"))
    content_alias = os.environ.get("BRIEFED_CONTENT_KEY_ALIAS", "")
    if not content_alias:
        raise RuntimeError("BRIEFED_CONTENT_KEY_ALIAS unset")

    async with httpx.AsyncClient() as http:
        llm = build_llm_client(
            settings=_settings,
            http_client=http,
            sanitizer=_build_redaction_chain(),
        )
        cipher = EnvelopeCipher(key_id=content_alias, client=_kms_client())
        async with get_sessionmaker()() as session:
            registry = PromptRegistry.load()
            await registry.sync_to_db(session)
            deps = SummarizeDeps(
                session=session,
                llm=llm,
                registry=registry,
                repo=SummariesRepo(cipher=cipher),
                content_cipher=cipher,
            )
            if isinstance(message, SummarizeEmailMessage):
                await handle_summarize_email(message, deps=deps)
            else:
                await handle_tech_news_cluster(message, deps=deps)
            await session.commit()


async def _handle_jobs_record(record: _SqsRecord) -> None:
    """Decode + dispatch one jobs-queue record (plan §14 Phase 4).

    Wires the LLM client + content cipher + prompt registry into the
    job-extract handler. The handler upserts a single ``job_matches`` row
    keyed by ``email_id`` and writes one ``prompt_call_log`` row.

    Args:
        record: Raw SQS record from the event envelope.
    """
    import os

    import httpx

    from app.core.security import EnvelopeCipher
    from app.db.session import get_sessionmaker
    from app.llm.factory import build_llm_client
    from app.services.jobs import JobMatchesRepo, parse_job_extract_body
    from app.services.prompts.registry import PromptRegistry
    from app.workers.handlers.jobs import JobExtractDeps, handle_job_extract

    message = parse_job_extract_body(record.get("body", "{}"))
    content_alias = os.environ.get("BRIEFED_CONTENT_KEY_ALIAS", "")
    if not content_alias:
        raise RuntimeError("BRIEFED_CONTENT_KEY_ALIAS unset")

    async with httpx.AsyncClient() as http:
        llm = build_llm_client(
            settings=_settings,
            http_client=http,
            sanitizer=_build_redaction_chain(),
        )
        cipher = EnvelopeCipher(key_id=content_alias, client=_kms_client())
        async with get_sessionmaker()() as session:
            registry = PromptRegistry.load()
            await registry.sync_to_db(session)
            deps = JobExtractDeps(
                session=session,
                llm=llm,
                registry=registry,
                repo=JobMatchesRepo(cipher=cipher),
                content_cipher=cipher,
            )
            await handle_job_extract(message, deps=deps)
            await session.commit()


async def _handle_unsubscribe_record(record: _SqsRecord) -> None:
    """Decode + dispatch one unsubscribe-queue record (plan §14 Phase 5).

    Wires the LLM client + content cipher + prompt registry into the
    hygiene handler. The handler runs the 30-day SQL aggregate, scores
    every sender, invokes the borderline LLM on 2-of-3 rule hits, and
    upserts :class:`app.db.models.UnsubscribeSuggestion` rows.

    Args:
        record: Raw SQS record from the event envelope.
    """
    import os

    import httpx

    from app.core.security import EnvelopeCipher
    from app.db.session import get_sessionmaker
    from app.llm.factory import build_llm_client
    from app.services.prompts.registry import PromptRegistry
    from app.services.unsubscribe import (
        UnsubscribeSuggestionsRepo,
        parse_unsubscribe_body,
    )
    from app.workers.handlers.unsubscribe import (
        UnsubscribeDeps,
        handle_unsubscribe,
    )

    message = parse_unsubscribe_body(record.get("body", "{}"))
    content_alias = os.environ.get("BRIEFED_CONTENT_KEY_ALIAS", "")
    if not content_alias:
        raise RuntimeError("BRIEFED_CONTENT_KEY_ALIAS unset")

    async with httpx.AsyncClient() as http:
        llm = build_llm_client(
            settings=_settings,
            http_client=http,
            sanitizer=_build_redaction_chain(),
        )
        cipher = EnvelopeCipher(key_id=content_alias, client=_kms_client())
        async with get_sessionmaker()() as session:
            registry = PromptRegistry.load()
            await registry.sync_to_db(session)
            deps = UnsubscribeDeps(
                session=session,
                llm=llm,
                registry=registry,
                repo=UnsubscribeSuggestionsRepo(cipher=cipher),
            )
            await handle_unsubscribe(message, deps=deps)
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
                sqs=_sqs_client(),
                ingest_queue_url=queue_url,
                store_raw_mime=os.environ.get("BRIEFED_STORE_RAW_MIME", "0") == "1",
            )
            return await run_fanout(deps=deps, user_id=user_filter)

    enqueued = asyncio.run(_run())
    logger.info("fanout_handler.completed", accounts_enqueued=enqueued)
    return {"accounts_enqueued": enqueued}
