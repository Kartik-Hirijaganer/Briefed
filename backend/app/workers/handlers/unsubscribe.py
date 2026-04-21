"""Unsubscribe / hygiene SQS handler (plan §14 Phase 5).

One invocation processes one :class:`UnsubscribeMessage`. The handler
is deliberately thin: it resolves the borderline prompt, then hands off
to :func:`app.services.unsubscribe.aggregator.rank_senders`.

Retry semantics:

* Missing connected-account row → surfaces as :class:`LookupError`;
  SQS re-delivers and the row eventually reappears or the message
  goes to the DLQ once the redrive policy exhausts.
* Missing ``prompt_versions`` row → same handling: the cold-start
  ``registry.sync_to_db`` in the worker entrypoint should have
  populated it; if it did not, re-delivery gives it another shot.
* :class:`app.llm.client.LLMClientError` is already caught inside
  :func:`rank_senders` — borderline senders whose LLM call fails are
  skipped (counted in :attr:`RankOutcome.llm_errors`) rather than
  failing the whole batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.services.unsubscribe.aggregator import (
    load_prompt_version_row,
    rank_senders,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.client import LLMClient
    from app.services.prompts.registry import PromptRegistry
    from app.services.unsubscribe.aggregator import RankOutcome
    from app.services.unsubscribe.repository import UnsubscribeSuggestionsRepo
    from app.workers.messages import UnsubscribeMessage


logger = get_logger(__name__)


@dataclass
class UnsubscribeDeps:
    """Collaborators the unsubscribe handler needs.

    Attributes:
        session: Open :class:`AsyncSession`.
        llm: Configured :class:`LLMClient` for borderline calls.
        registry: In-memory :class:`PromptRegistry`.
        repo: Encrypt-on-write
            :class:`UnsubscribeSuggestionsRepo`.
    """

    session: AsyncSession
    llm: LLMClient
    registry: PromptRegistry
    repo: UnsubscribeSuggestionsRepo


async def handle_unsubscribe(
    message: UnsubscribeMessage,
    *,
    deps: UnsubscribeDeps,
) -> RankOutcome:
    """Process one :class:`UnsubscribeMessage`.

    Args:
        message: The validated payload.
        deps: :class:`UnsubscribeDeps`.

    Returns:
        :class:`app.services.unsubscribe.aggregator.RankOutcome` for
        observability.

    Raises:
        LookupError: When the prompt-version row or target
            connected-account row is missing (SQS re-delivers).
    """
    prompt = deps.registry.get(message.prompt_name, version=message.prompt_version)
    prompt_row = await load_prompt_version_row(
        session=deps.session,
        content_hash=prompt.content_hash,
    )

    started = utcnow()
    outcome = await rank_senders(
        session=deps.session,
        user_id=message.user_id,
        account_id=message.account_id,
        llm=deps.llm,
        prompt=prompt,
        prompt_version_id=prompt_row.id,
        repo=deps.repo,
        run_id=message.run_id,
    )
    logger.info(
        "unsubscribe.handler.completed",
        account_id=str(message.account_id),
        run_id=str(message.run_id) if message.run_id else None,
        candidates=outcome.candidates,
        rule=outcome.rule_recommendations,
        model=outcome.model_recommendations,
        skipped=outcome.skipped,
        llm_errors=outcome.llm_errors,
        elapsed_ms=int((utcnow() - started).total_seconds() * 1000),
    )
    return outcome


__all__ = ["UnsubscribeDeps", "handle_unsubscribe"]
