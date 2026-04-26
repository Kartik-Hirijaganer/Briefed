"""``/api/v1/rubric`` router — CRUD over the user's classification rules.

Powers the Phase 6 settings UI and the Phase 2 `rubric change
propagates within one run` exit criterion: updating a rule bumps its
``version`` so the next classify run picks up the new snapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import current_user_id, db_session
from app.db.models import RubricRule
from app.schemas.rubric import (
    RubricRuleIn,
    RubricRuleOut,
    RubricRulesListResponse,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/rubric", tags=["rubric"])


@router.get(
    "",
    response_model=RubricRulesListResponse,
    summary="List classification rules",
)
async def list_rules(
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> RubricRulesListResponse:
    """Return every rubric rule the authenticated user owns.

    Args:
        user_id: Authenticated owner.
        session: Active async session.

    Returns:
        :class:`RubricRulesListResponse` with rules ordered by
        ``priority DESC``.
    """
    rows = (
        (
            await session.execute(
                select(RubricRule)
                .where(RubricRule.user_id == user_id)
                .order_by(RubricRule.priority.desc()),
            )
        )
        .scalars()
        .all()
    )
    return RubricRulesListResponse(
        rules=tuple(RubricRuleOut.model_validate(row) for row in rows),
    )


@router.post(
    "",
    response_model=RubricRuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a classification rule",
)
async def create_rule(
    payload: RubricRuleIn,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> RubricRuleOut:
    """Insert a new rule for the authenticated user.

    Args:
        payload: Request body.
        user_id: Authenticated owner.
        session: Active async session.

    Returns:
        The created :class:`RubricRuleOut`.
    """
    row = RubricRule(
        user_id=user_id,
        priority=payload.priority,
        match=payload.match,
        action=payload.action,
        version=1,
        active=payload.active,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return RubricRuleOut.model_validate(row)


@router.put(
    "/{rule_id}",
    response_model=RubricRuleOut,
    summary="Replace a classification rule",
)
async def update_rule(
    rule_id: UUID,
    payload: RubricRuleIn,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> RubricRuleOut:
    """Replace ``rule_id``'s predicate + action, bumping ``version``.

    Args:
        rule_id: Target rule.
        payload: Request body.
        user_id: Authenticated owner.
        session: Active async session.

    Returns:
        The updated :class:`RubricRuleOut`.

    Raises:
        HTTPException: 404 when the rule does not belong to the caller.
    """
    row = await session.get(RubricRule, rule_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="rule not found")
    row.priority = payload.priority
    row.match = payload.match
    row.action = payload.action
    row.active = payload.active
    row.version = row.version + 1
    await session.flush()
    await session.refresh(row)
    return RubricRuleOut.model_validate(row)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a classification rule",
)
async def delete_rule(
    rule_id: UUID,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Hard-delete ``rule_id``.

    Args:
        rule_id: Target rule.
        user_id: Authenticated owner.
        session: Active async session.

    Raises:
        HTTPException: 404 when the rule does not belong to the caller.
    """
    row = await session.get(RubricRule, rule_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="rule not found")
    await session.delete(row)
