"""Summarize SQS handler (plan §14 Phase 3).

One invocation processes one :class:`SummarizeEmailMessage` or one
:class:`TechNewsClusterMessage`. The handler is deliberately thin: it
wires the session, prompt registry, LLM client, and repo, then hands
off to :mod:`app.services.summarization`.

Retry semantics:

* Missing email / cluster row → log + succeed (nothing left to do).
* Missing prompt version row → raises so SQS re-delivers.
* :class:`app.llm.client.LLMClientError` is already handled inside the
  pipeline (``ok=False`` outcome) — we do not retry at the SQS level
  because the breaker already backed off.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import PromptVersion
from app.observability.metrics import (
    emit_summarize_cluster_metric,
    emit_summarize_email_metric,
)
from app.services.summarization import (
    ClusterRouter,
    SummariesRepo,
    SummarizeInputs,
    TechNewsInputs,
    cluster_and_summarize,
    load_default_router,
    summarize_email,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher
    from app.llm.client import LLMClient
    from app.services.prompts.registry import PromptRegistry
    from app.services.summarization.relevant import SummarizeOutcome
    from app.services.summarization.tech_news import TechNewsOutcome
    from app.workers.messages import SummarizeEmailMessage, TechNewsClusterMessage


logger = get_logger(__name__)


@dataclass
class SummarizeDeps:
    """Collaborators the summarize handler needs.

    Attributes:
        session: Open :class:`AsyncSession`.
        llm: Configured :class:`LLMClient`.
        registry: In-memory :class:`PromptRegistry`.
        repo: Encrypt-on-write :class:`SummariesRepo`.
        router: Optional pre-loaded :class:`ClusterRouter`. Handler
            lazy-loads from the DB when ``None``.
        content_cipher: Optional content-at-rest cipher for body excerpts.
    """

    session: AsyncSession
    llm: LLMClient
    registry: PromptRegistry
    repo: SummariesRepo
    router: ClusterRouter | None = None
    content_cipher: EnvelopeCipher | None = None


async def handle_summarize_email(
    message: SummarizeEmailMessage,
    *,
    deps: SummarizeDeps,
) -> SummarizeOutcome:
    """Process one :class:`SummarizeEmailMessage`.

    Args:
        message: The validated payload.
        deps: :class:`SummarizeDeps`.

    Returns:
        :class:`SummarizeOutcome` for observability.

    Raises:
        LookupError: When the target email or prompt version row is
            missing (SQS will re-deliver).
    """
    prompt = deps.registry.get(message.prompt_name, version=message.prompt_version)
    prompt_row = await _load_prompt_row(
        session=deps.session,
        content_hash=prompt.content_hash,
        message=f"{message.prompt_name} v{message.prompt_version}",
    )

    started = utcnow()
    outcome = await summarize_email(
        SummarizeInputs(
            email_id=message.email_id,
            user_id=message.user_id,
            prompt=prompt,
            prompt_version_id=prompt_row.id,
            llm=deps.llm,
            repo=deps.repo,
            batch_id=message.batch_id,
            content_cipher=deps.content_cipher,
        ),
        session=deps.session,
        run_id=message.run_id,
    )
    emit_summarize_email_metric(
        ok=outcome.ok,
        confidence=outcome.confidence,
        cache_hit=outcome.cache_hit,
        tokens_in=outcome.tokens_in,
        tokens_out=outcome.tokens_out,
        cost_usd=outcome.cost_usd,
        fallback_used=outcome.fallback_used,
        batch=message.batch_id is not None,
    )
    logger.info(
        "summarize.email.handler.completed",
        email_id=str(outcome.email_id),
        ok=outcome.ok,
        confidence=outcome.confidence,
        cache_hit=outcome.cache_hit,
        fallback_used=outcome.fallback_used,
        elapsed_ms=int((utcnow() - started).total_seconds() * 1000),
    )
    return outcome


async def handle_tech_news_cluster(
    message: TechNewsClusterMessage,
    *,
    deps: SummarizeDeps,
) -> TechNewsOutcome:
    """Process one :class:`TechNewsClusterMessage`.

    Args:
        message: The validated payload.
        deps: :class:`SummarizeDeps`.

    Returns:
        :class:`TechNewsOutcome` for observability.

    Raises:
        LookupError: When the prompt version row is missing.
    """
    prompt = deps.registry.get(message.prompt_name, version=message.prompt_version)
    prompt_row = await _load_prompt_row(
        session=deps.session,
        content_hash=prompt.content_hash,
        message=f"{message.prompt_name} v{message.prompt_version}",
    )
    router = deps.router if deps.router is not None else await load_default_router(deps.session)

    started = utcnow()
    outcome = await cluster_and_summarize(
        TechNewsInputs(
            user_id=message.user_id,
            run_id=message.run_id,
            email_ids=message.email_ids,
            prompt=prompt,
            prompt_version_id=prompt_row.id,
            llm=deps.llm,
            repo=deps.repo,
            router=router,
            min_cluster_size=message.min_cluster_size,
            max_cluster_size=message.max_cluster_size,
            content_cipher=deps.content_cipher,
        ),
        session=deps.session,
    )
    emit_summarize_cluster_metric(
        clusters_created=outcome.clusters_created,
        clusters_summarized=outcome.clusters_summarized,
        clusters_failed=outcome.clusters_failed,
        tokens_in=outcome.total_tokens_in,
        tokens_out=outcome.total_tokens_out,
        cost_usd=outcome.total_cost_usd,
        cache_hits=outcome.cache_hits,
    )
    logger.info(
        "summarize.cluster.handler.completed",
        clusters_created=outcome.clusters_created,
        clusters_summarized=outcome.clusters_summarized,
        clusters_skipped_small=outcome.clusters_skipped_small,
        clusters_failed=outcome.clusters_failed,
        elapsed_ms=int((utcnow() - started).total_seconds() * 1000),
    )
    return outcome


async def _load_prompt_row(
    *,
    session: AsyncSession,
    content_hash: bytes,
    message: str,
) -> PromptVersion:
    """Resolve the ``prompt_versions`` row matching ``content_hash``.

    Args:
        session: Active async session.
        content_hash: SHA-256 digest from the prompt registry.
        message: Human-readable name used in the error path.

    Returns:
        Attached :class:`PromptVersion` row.

    Raises:
        LookupError: When no row exists for the digest.
    """
    row = (
        (
            await session.execute(
                select(PromptVersion).where(PromptVersion.content_hash == content_hash),
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise LookupError(f"prompt_versions row missing for {message}")
    return row


__all__ = [
    "SummarizeDeps",
    "handle_summarize_email",
    "handle_tech_news_cluster",
]
