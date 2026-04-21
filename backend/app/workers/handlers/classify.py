"""Classify SQS handler (plan §14 Phase 2).

One invocation processes one :class:`ClassifyMessage` and produces a
:class:`Classification` row plus one :class:`PromptCallLog` row.

Retry semantics:

* Missing email row → treat as dropped (successful handle — nothing
  to classify); log and return.
* Missing prompt version → raises; SQS re-delivers.
* :class:`app.llm.client.LLMClientError` is handled inside the pipeline
  by writing a ``needs_review`` row with ``status='error'`` — we do not
  retry at the SQS level because the breaker already backed off.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.clock import utcnow
from app.core.logging import get_logger
from app.db.models import PromptVersion
from app.services.classification.pipeline import ClassifyInputs, classify_one
from app.services.classification.repository import ClassificationsRepo
from app.services.classification.rubric import load_default_rules
from app.services.prompts.registry import PromptRegistry

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher
    from app.llm.client import LLMClient
    from app.services.classification.pipeline import ClassifyOutcome
    from app.workers.messages import ClassifyMessage


logger = get_logger(__name__)


@dataclass
class ClassifyDeps:
    """Collaborators the classify handler needs.

    Attributes:
        session: Open :class:`AsyncSession`.
        llm: Configured :class:`LLMClient`.
        registry: In-memory :class:`PromptRegistry`.
        repo: Encrypt-on-write :class:`ClassificationsRepo`.
        content_cipher: Optional content-at-rest cipher for body excerpts.
    """

    session: AsyncSession
    llm: LLMClient
    registry: PromptRegistry
    repo: ClassificationsRepo
    content_cipher: EnvelopeCipher | None = None


async def handle_classify(
    message: ClassifyMessage,
    *,
    deps: ClassifyDeps,
) -> ClassifyOutcome:
    """Process one :class:`ClassifyMessage`.

    Args:
        message: The validated payload.
        deps: :class:`ClassifyDeps`.

    Returns:
        :class:`ClassifyOutcome` summarising the decision.

    Raises:
        LookupError: When the target email or prompt version is missing.
    """
    prompt = deps.registry.get(message.prompt_name, version=message.prompt_version)

    prompt_row = (
        (
            await deps.session.execute(
                select(PromptVersion).where(
                    PromptVersion.content_hash == prompt.content_hash,
                ),
            )
        )
        .scalars()
        .first()
    )
    if prompt_row is None:
        raise LookupError(
            f"prompt_versions row missing for {message.prompt_name} v{message.prompt_version}",
        )

    engine = await load_default_rules(deps.session, user_id=message.user_id)
    inputs = ClassifyInputs(
        email_id=message.email_id,
        user_id=message.user_id,
        prompt=prompt,
        llm=deps.llm,
        repo=deps.repo,
        prompt_version_id=prompt_row.id,
        content_cipher=deps.content_cipher,
    )

    started = utcnow()
    outcome = await classify_one(
        inputs,
        session=deps.session,
        rule_engine=engine,
        run_id=message.run_id,
    )
    logger.info(
        "classify.handler.completed",
        email_id=str(outcome.email_id),
        label=outcome.label,
        decision_source=outcome.decision_source,
        score=outcome.score,
        llm_used=outcome.llm_used,
        cost_usd=str(outcome.cost_usd),
        elapsed_ms=int((utcnow() - started).total_seconds() * 1000),
    )
    return outcome


__all__ = ["ClassifyDeps", "handle_classify"]


_ = UUID  # keep UUID referenced for workers who import via * semantics
