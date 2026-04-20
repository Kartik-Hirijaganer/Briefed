"""Job-extract SQS handler (plan §14 Phase 4).

One invocation processes one :class:`JobExtractMessage`. The handler is
deliberately thin: it wires the session, prompt registry, LLM client,
and repo, then hands off to :func:`app.services.jobs.extractor.extract_job`.

Retry semantics:

* Missing email row → log + succeed (nothing to do).
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
from app.services.jobs.extractor import ExtractInputs, extract_job
from app.services.jobs.repository import JobMatchesRepo

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.client import LLMClient
    from app.services.jobs.extractor import ExtractOutcome
    from app.services.prompts.registry import PromptRegistry
    from app.workers.messages import JobExtractMessage


logger = get_logger(__name__)


@dataclass
class JobExtractDeps:
    """Collaborators the job-extract handler needs.

    Attributes:
        session: Open :class:`AsyncSession`.
        llm: Configured :class:`LLMClient`.
        registry: In-memory :class:`PromptRegistry`.
        repo: Encrypt-on-write :class:`JobMatchesRepo`.
        reader_profile: Optional override of the default reader
            context rendered into the prompt.
    """

    session: AsyncSession
    llm: LLMClient
    registry: PromptRegistry
    repo: JobMatchesRepo
    reader_profile: str | None = None


async def handle_job_extract(
    message: JobExtractMessage,
    *,
    deps: JobExtractDeps,
) -> ExtractOutcome:
    """Process one :class:`JobExtractMessage`.

    Args:
        message: The validated payload.
        deps: :class:`JobExtractDeps`.

    Returns:
        :class:`ExtractOutcome` for observability.

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
    outcome = await extract_job(
        ExtractInputs(
            email_id=message.email_id,
            user_id=message.user_id,
            prompt=prompt,
            prompt_version_id=prompt_row.id,
            llm=deps.llm,
            repo=deps.repo,
            reader_profile=deps.reader_profile,
        ),
        session=deps.session,
        run_id=message.run_id,
    )
    logger.info(
        "jobs.extract.handler.completed",
        email_id=str(outcome.email_id),
        ok=outcome.ok,
        match_score=outcome.match_score,
        passed_filter=outcome.passed_filter,
        corroborated=outcome.corroborated,
        cache_hit=outcome.cache_hit,
        fallback_used=outcome.fallback_used,
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


__all__ = ["JobExtractDeps", "handle_job_extract"]
