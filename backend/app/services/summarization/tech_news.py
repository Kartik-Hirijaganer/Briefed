"""Tech-news clustering + group summary (plan §14 Phase 3).

Given the set of newsletter emails for a run, the module:

1. Routes each email to a ``cluster_key`` via
   :class:`app.services.summarization.cluster_router.ClusterRouter`.
2. Groups emails per cluster; skips clusters smaller than the min-size.
3. Upserts one :class:`app.db.models.TechNewsCluster` row + one
   :class:`TechNewsClusterMember` per source email.
4. Renders the ``newsletter_group`` prompt with the clustered payload.
5. Calls :class:`app.llm.client.LLMClient`; validates
   :class:`app.llm.schemas.TechNewsClusterSummary`; upserts one
   :class:`app.db.models.Summary` row via :class:`SummariesRepo`.
6. Appends :class:`app.db.models.PromptCallLog` rows.

The module is careful to stay deterministic across runs: cluster
ordering is sender-count DESC then cluster_key ASC, and source emails
inside a cluster are ordered by ``internal_date`` then ``id`` so the
rendered `newsletters_block` is stable. Determinism matters for the
eval suite.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import (
    Email,
    EmailContentBlob,
    PromptCallLog,
    TechNewsCluster,
    TechNewsClusterMember,
)
from app.llm.client import (
    LLMClient,
    LLMClientError,
    PromptCallRecord,
    render_prompt,
)
from app.llm.schemas import TechNewsClusterSummary
from app.services.ingestion.content import decrypt_excerpt
from app.services.summarization.cluster_router import ClusterRoute, ClusterRouter
from app.services.summarization.repository import (
    SummariesRepo,
    SummaryTechNewsWrite,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher
    from app.services.prompts.registry import RegisteredPrompt


logger = get_logger(__name__)

_DEFAULT_MIN_CLUSTER_SIZE = 2
"""Clusters with fewer than this many emails are skipped (plan §14 Phase 3)."""

_DEFAULT_MAX_CLUSTER_SIZE = 8
"""Cap per-cluster source count so prompts stay well under the token limit."""

_PER_SOURCE_EXCERPT_CHARS = 1200
"""Hard cap on plaintext excerpt per source newsletter sent to the model."""


@dataclass(frozen=True)
class TechNewsInputs:
    """Everything the pipeline needs to cluster + summarize one run.

    Attributes:
        user_id: Owner — bound into the encryption context.
        run_id: Optional digest-run scope.
        email_ids: Ordered list of newsletter email ids to consider.
        prompt: Loaded :class:`RegisteredPrompt` for ``newsletter_group``.
        prompt_version_id: ``prompt_versions.id`` matching ``prompt``.
        llm: Configured :class:`LLMClient`.
        repo: Encrypt-on-write :class:`SummariesRepo`.
        router: Pre-loaded :class:`ClusterRouter`.
        min_cluster_size: Skip clusters below this size (default 2).
        max_cluster_size: Cap cluster size; extra sources are dropped
            from the prompt but remain on disk as members (default 8).
        batch_id: Optional Batch API job id when driven asynchronously.
        content_cipher: Optional content-at-rest cipher for body excerpts.
    """

    user_id: UUID
    run_id: UUID | None
    email_ids: tuple[UUID, ...]
    prompt: RegisteredPrompt
    prompt_version_id: UUID
    llm: LLMClient
    repo: SummariesRepo
    router: ClusterRouter
    min_cluster_size: int = _DEFAULT_MIN_CLUSTER_SIZE
    max_cluster_size: int = _DEFAULT_MAX_CLUSTER_SIZE
    batch_id: str | None = None
    content_cipher: EnvelopeCipher | None = None


@dataclass(frozen=True)
class TechNewsOutcome:
    """Result returned to the worker handler.

    Attributes:
        clusters_created: Count of :class:`TechNewsCluster` rows
            created or updated.
        clusters_summarized: Count of cluster summary rows written.
        clusters_skipped_small: Count of clusters below the min size.
        clusters_failed: Count of clusters that hit an LLM error.
        total_tokens_in: Sum of input tokens across cluster calls.
        total_tokens_out: Sum of output tokens across cluster calls.
        total_cost_usd: Sum of per-cluster cost estimates.
        cache_hits: Count of cluster calls with cache-read > 0.
    """

    clusters_created: int
    clusters_summarized: int
    clusters_skipped_small: int
    clusters_failed: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: Decimal
    cache_hits: int


async def cluster_and_summarize(
    inputs: TechNewsInputs,
    *,
    session: AsyncSession,
) -> TechNewsOutcome:
    """Cluster the supplied newsletters and summarize each cluster.

    Args:
        inputs: Collaborator bundle.
        session: Active async session (caller owns commit).

    Returns:
        :class:`TechNewsOutcome`.
    """
    if not inputs.email_ids:
        return _empty_outcome()

    rows = await _load_emails(session, email_ids=inputs.email_ids)
    grouped: dict[str, list[tuple[Email, ClusterRoute]]] = defaultdict(list)
    route_topics: dict[str, str] = {}
    for email_row in rows:
        list_id = _extract_list_id(email_row)
        route = inputs.router.route(
            from_addr=email_row.from_addr,
            subject=email_row.subject,
            list_id=list_id,
        )
        grouped[route.cluster_key].append((email_row, route))
        route_topics.setdefault(route.cluster_key, route.topic_hint)

    sorted_keys = sorted(grouped.keys(), key=lambda key: (-len(grouped[key]), key))

    clusters_created = 0
    clusters_summarized = 0
    clusters_skipped = 0
    clusters_failed = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = Decimal("0")
    cache_hits = 0

    for cluster_key in sorted_keys:
        members = grouped[cluster_key]
        if len(members) < inputs.min_cluster_size:
            clusters_skipped += 1
            continue

        members.sort(key=lambda pair: (pair[0].internal_date, pair[0].id))
        capped_members = members[: inputs.max_cluster_size]
        topic_hint = route_topics.get(cluster_key, "")

        cluster_row = await _upsert_cluster(
            session,
            user_id=inputs.user_id,
            run_id=inputs.run_id,
            cluster_key=cluster_key,
            topic_hint=topic_hint,
            members=[pair[0] for pair in capped_members],
        )
        clusters_created += 1

        rendered = render_prompt(
            inputs.prompt.spec,
            variables={
                "cluster_key": cluster_key,
                "topic_hint": topic_hint or "",
                "newsletters_block": _render_newsletters_block(
                    capped_members,
                    user_id=inputs.user_id,
                    cipher=inputs.content_cipher,
                ),
            },
        )

        async def _log_call(
            record: PromptCallRecord,
            _run_id: UUID | None = inputs.run_id,
        ) -> None:
            await _persist_call_log(
                session=session,
                record=record,
                run_id=_run_id,
            )

        try:
            response = await inputs.llm.call(
                spec=inputs.prompt.spec,
                rendered_prompt=rendered,
                schema=TechNewsClusterSummary,
                prompt_version_id=inputs.prompt_version_id,
                email_id=None,
                run_id=inputs.run_id,
                log_call=_log_call,
            )
        except LLMClientError as exc:
            clusters_failed += 1
            logger.warning(
                "summarize.tech_news.llm_failed",
                cluster_key=cluster_key,
                error=str(exc),
            )
            continue

        summary = response.parsed
        assert isinstance(summary, TechNewsClusterSummary)
        body_md = _render_cluster_body_md(summary)
        cache_hit = response.call_result.tokens_cache_read > 0

        sources = summary.sources or tuple(email_row.subject for email_row, _ in capped_members)
        await inputs.repo.upsert_tech_news_cluster(
            session,
            SummaryTechNewsWrite(
                cluster_id=cluster_row.id,
                user_id=inputs.user_id,
                prompt_version_id=inputs.prompt_version_id,
                model=response.call_result.model,
                tokens_in=response.call_result.tokens_in,
                tokens_out=response.call_result.tokens_out,
                body_md=body_md,
                sources=tuple(sources),
                confidence=_to_decimal(summary.confidence),
                cache_hit=cache_hit,
                batch_id=inputs.batch_id,
            ),
        )
        clusters_summarized += 1
        total_tokens_in += response.call_result.tokens_in
        total_tokens_out += response.call_result.tokens_out
        total_cost += response.call_result.cost_usd
        if cache_hit:
            cache_hits += 1

    outcome = TechNewsOutcome(
        clusters_created=clusters_created,
        clusters_summarized=clusters_summarized,
        clusters_skipped_small=clusters_skipped,
        clusters_failed=clusters_failed,
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        total_cost_usd=total_cost,
        cache_hits=cache_hits,
    )
    logger.info(
        "summarize.tech_news.completed",
        clusters_created=clusters_created,
        clusters_summarized=clusters_summarized,
        clusters_skipped_small=clusters_skipped,
        clusters_failed=clusters_failed,
        tokens_in=total_tokens_in,
        tokens_out=total_tokens_out,
        cost_usd=str(total_cost),
        cache_hits=cache_hits,
    )
    return outcome


def _render_cluster_body_md(summary: TechNewsClusterSummary) -> str:
    """Render a cluster summary into digest-ready markdown."""
    parts: list[str] = [f"**{summary.headline}**"]
    if summary.bullets:
        parts.append("")
        parts.extend(f"- {item}" for item in summary.bullets)
    return "\n".join(parts).strip()


def _render_newsletters_block(
    members: list[tuple[Email, ClusterRoute]],
    *,
    user_id: UUID,
    cipher: EnvelopeCipher | None,
) -> str:
    """Render the per-source block the prompt consumes."""
    sections: list[str] = []
    for email_row, _route in members:
        excerpt = _excerpt_for(
            email_row,
            user_id=user_id,
            cipher=cipher,
        )[:_PER_SOURCE_EXCERPT_CHARS]
        subject = email_row.subject.strip() or "(no subject)"
        sections.append(f"--- source subject: {subject} ---\n{excerpt}".rstrip())
    return "\n".join(sections)


async def _load_emails(
    session: AsyncSession,
    *,
    email_ids: tuple[UUID, ...],
) -> list[Email]:
    """Fetch email rows preserving insertion order."""
    stmt = select(Email).where(Email.id.in_(email_ids))
    fetched: Iterable[Email] = (await session.execute(stmt)).scalars().all()
    by_id: dict[UUID, Email] = {row.id: row for row in fetched}
    return [by_id[email_id] for email_id in email_ids if email_id in by_id]


async def _upsert_cluster(
    session: AsyncSession,
    *,
    user_id: UUID,
    run_id: UUID | None,
    cluster_key: str,
    topic_hint: str,
    members: list[Email],
) -> TechNewsCluster:
    """Upsert a :class:`TechNewsCluster` + refresh its membership list."""
    existing = (
        (
            await session.execute(
                select(TechNewsCluster).where(
                    TechNewsCluster.user_id == user_id,
                    TechNewsCluster.cluster_key == cluster_key,
                    TechNewsCluster.run_id == run_id,
                ),
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        existing = TechNewsCluster(
            user_id=user_id,
            run_id=run_id,
            cluster_key=cluster_key,
            topic_hint=topic_hint,
            member_count=len(members),
        )
        session.add(existing)
        await session.flush()
    else:
        existing.topic_hint = topic_hint
        existing.member_count = len(members)

    existing_members = (
        (
            await session.execute(
                select(TechNewsClusterMember).where(
                    TechNewsClusterMember.cluster_id == existing.id,
                ),
            )
        )
        .scalars()
        .all()
    )
    for old in existing_members:
        await session.delete(old)
    await session.flush()

    for idx, email_row in enumerate(members):
        session.add(
            TechNewsClusterMember(
                cluster_id=existing.id,
                email_id=email_row.id,
                sort_order=idx,
            ),
        )
    await session.flush()
    return existing


async def _persist_call_log(
    *,
    session: AsyncSession,
    record: PromptCallRecord,
    run_id: UUID | None,
) -> None:
    """Insert one :class:`PromptCallLog` row from a client record."""
    session.add(
        PromptCallLog(
            prompt_version_id=record.prompt_version_id,
            email_id=record.email_id,
            model=record.model,
            tokens_in=record.tokens_in,
            tokens_out=record.tokens_out,
            tokens_cache_read=record.tokens_cache_read,
            tokens_cache_write=record.tokens_cache_write,
            cost_usd=record.cost_usd,
            latency_ms=record.latency_ms,
            status=record.status,
            provider=record.provider,
            run_id=run_id,
            redaction_summary=record.redaction_counts,
        ),
    )
    await session.flush()


def _excerpt_for(
    row: Email,
    *,
    user_id: UUID,
    cipher: EnvelopeCipher | None,
) -> str:
    """Return the best plaintext excerpt for the clustering prompt."""
    blob: EmailContentBlob | None = row.body
    excerpt = decrypt_excerpt(blob, user_id=user_id, cipher=cipher)
    if excerpt:
        return excerpt
    return row.snippet or ""


def _extract_list_id(row: Email) -> str | None:
    """Pull the raw ``List-ID`` header out of the normalized unsubscribe blob.

    The Gmail parser stores ``list_unsubscribe`` as JSON; the actual
    ``List-ID`` header — when present — is attached under
    ``headers.list_id`` alongside the unsubscribe info. Handle both the
    plain-string and dict shapes defensively.
    """
    raw = row.list_unsubscribe
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        maybe = raw.get("list_id")
        if isinstance(maybe, str):
            return maybe.strip()
    return None


def _empty_outcome() -> TechNewsOutcome:
    """Return a zeroed :class:`TechNewsOutcome` for the empty-input fast path."""
    return TechNewsOutcome(
        clusters_created=0,
        clusters_summarized=0,
        clusters_skipped_small=0,
        clusters_failed=0,
        total_tokens_in=0,
        total_tokens_out=0,
        total_cost_usd=Decimal("0"),
        cache_hits=0,
    )


def _to_decimal(value: float) -> Decimal:
    """Convert a confidence float to a quantized Decimal (3 dp)."""
    return Decimal(str(value)).quantize(Decimal("0.001"))


__all__ = [
    "TechNewsInputs",
    "TechNewsOutcome",
    "cluster_and_summarize",
]

_ = utcnow  # keep clock import live so workers using * semantics work.
