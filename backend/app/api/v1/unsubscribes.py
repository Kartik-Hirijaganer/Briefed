"""``/api/v1/unsubscribes`` + ``/api/v1/hygiene`` routers (plan §14 Phase 5).

Three surfaces:

* ``GET /unsubscribes`` — top-N recommended senders to unsubscribe,
  highest confidence first. ``dismissed`` rows are hidden by default
  (``include_dismissed=true`` surfaces them for an undo UI).
* ``POST /unsubscribes/{id}/dismiss`` — record user-side dismissal;
  the aggregate preserves this across re-runs.
* ``POST /unsubscribes/{id}/confirm`` — record that the user clicked
  through to the provider's action URL. Release 1.0.0 is recommend-
  only (ADR 0006) so we do **not** touch Gmail — we dismiss the row
  with an audit log entry so the sender does not re-surface.

The ``GET /hygiene/stats`` endpoint returns small aggregates over the
same table for the dashboard's hygiene-stats card.

Rationale text is envelope-encrypted at rest; this router decrypts
via :class:`app.services.unsubscribe.repository.UnsubscribeSuggestionsRepo`
so the response never carries ciphertext. The decrypt path is wrapped
in a content cipher when ``settings.content_key_alias`` is configured;
local + test environments fall back to the pass-through repo mode.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import current_user_id, db_session
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.db.models import ConnectedAccount, UnsubscribeSuggestion
from app.schemas.unsubscribe import (
    DomainWasteEntry,
    HygieneStatsResponse,
    UnsubscribeActionOut,
    UnsubscribeSuggestionOut,
    UnsubscribeSuggestionsListResponse,
)
from app.services.unsubscribe.repository import UnsubscribeSuggestionsRepo

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import KmsClient


unsubscribes_router = APIRouter(prefix="/unsubscribes", tags=["unsubscribes"])
hygiene_router = APIRouter(prefix="/hygiene", tags=["hygiene"])

_TOP_DOMAIN_CAP = 10
"""Plan §14 Phase 5 — dashboard card shows at most 10 top domains."""

_RECOMMENDATION_CONFIDENCE_MIN = Decimal("0.800")
"""Policy gate: low-confidence model veto rows are audit rows, not recommendations."""


def _repo_for(settings: Settings) -> UnsubscribeSuggestionsRepo:
    """Return a repo wired with the content cipher when configured.

    Kept separate from the list handler so the dismiss / confirm
    endpoints can construct the repo without also running the
    decrypt helper.
    """
    if not settings.content_key_alias:
        return UnsubscribeSuggestionsRepo(cipher=None)
    import boto3  # type: ignore[import-untyped]

    from app.core.security import EnvelopeCipher

    return UnsubscribeSuggestionsRepo(
        cipher=EnvelopeCipher(
            key_id=settings.content_key_alias,
            client=cast("KmsClient", boto3.client("kms")),
        ),
    )


@unsubscribes_router.get(
    "",
    response_model=UnsubscribeSuggestionsListResponse,
    summary="List unsubscribe recommendations",
)
async def list_suggestions(
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
    include_dismissed: bool = Query(
        default=False,
        description="Include rows the user has dismissed (for an undo UI).",
    ),
    limit: int = Query(default=20, ge=1, le=100),
) -> UnsubscribeSuggestionsListResponse:
    """Return the caller's unsubscribe suggestions.

    Rows are scoped to the caller via
    ``UnsubscribeSuggestion.account_id -> ConnectedAccount.user_id``.
    Default order is ``confidence DESC`` so the most-actionable rows
    surface first.

    Args:
        user_id: Authenticated owner.
        session: Active async session.
        settings: Cached :class:`Settings`.
        include_dismissed: Override the curated default.
        limit: Maximum rows to return.

    Returns:
        :class:`UnsubscribeSuggestionsListResponse`.
    """
    stmt = (
        select(UnsubscribeSuggestion)
        .join(
            ConnectedAccount,
            ConnectedAccount.id == UnsubscribeSuggestion.account_id,
        )
        .where(ConnectedAccount.user_id == user_id)
        .order_by(
            UnsubscribeSuggestion.confidence.desc(),
            UnsubscribeSuggestion.frequency_30d.desc(),
        )
        .limit(limit)
    )
    if not include_dismissed:
        stmt = stmt.where(
            UnsubscribeSuggestion.dismissed.is_(False),
            UnsubscribeSuggestion.confidence >= _RECOMMENDATION_CONFIDENCE_MIN,
        )

    rows = (await session.execute(stmt)).scalars().all()
    repo = _repo_for(settings)
    suggestions = tuple(
        UnsubscribeSuggestionOut(
            id=row.id,
            sender_domain=row.sender_domain,
            sender_email=row.sender_email,
            frequency_30d=row.frequency_30d,
            engagement_score=row.engagement_score,
            waste_rate=row.waste_rate,
            confidence=row.confidence,
            decision_source=cast(
                Literal["rule", "model"],
                row.decision_source,
            ),
            category=None,
            rationale=repo.decrypt_rationale(row=row, user_id=user_id),
            list_unsubscribe=_action_from_json(row.list_unsubscribe),
            dismissed=row.dismissed,
            dismissed_at=row.dismissed_at,
            last_email_at=row.last_email_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    )
    return UnsubscribeSuggestionsListResponse(suggestions=suggestions)


@unsubscribes_router.post(
    "/{suggestion_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dismiss an unsubscribe suggestion",
)
async def dismiss_suggestion(
    suggestion_id: UUID,
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Mark ``suggestion_id`` as dismissed.

    The dismissal survives across aggregate re-runs: the repo's upsert
    path only replaces the numeric + rationale columns.

    Args:
        suggestion_id: Target suggestion.
        user_id: Authenticated owner.
        session: Active async session.

    Raises:
        HTTPException: 404 when the row does not belong to the caller.
    """
    row = await _load_owned(session, suggestion_id=suggestion_id, user_id=user_id)
    row.dismissed = True
    row.dismissed_at = utcnow()
    await session.flush()


@unsubscribes_router.post(
    "/{suggestion_id}/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirm the user acted on the unsubscribe suggestion",
)
async def confirm_suggestion(
    suggestion_id: UUID,
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> None:
    """Record that the user followed through on the recommendation.

    Release 1.0.0 is recommend-only (ADR 0006) — the server never
    reaches out to the provider. This endpoint marks the row
    ``dismissed=True`` so it no longer surfaces.

    Args:
        suggestion_id: Target suggestion.
        user_id: Authenticated owner.
        session: Active async session.

    Raises:
        HTTPException: 404 when the row does not belong to the caller.
    """
    row = await _load_owned(session, suggestion_id=suggestion_id, user_id=user_id)
    row.dismissed = True
    row.dismissed_at = utcnow()
    await session.flush()


@hygiene_router.get(
    "/stats",
    response_model=HygieneStatsResponse,
    summary="Inbox-hygiene summary counters",
)
async def hygiene_stats(
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
) -> HygieneStatsResponse:
    """Return small aggregates over the caller's suggestions.

    Args:
        user_id: Authenticated owner.
        session: Active async session.

    Returns:
        :class:`HygieneStatsResponse`.
    """
    base = (
        select(UnsubscribeSuggestion)
        .join(
            ConnectedAccount,
            ConnectedAccount.id == UnsubscribeSuggestion.account_id,
        )
        .where(ConnectedAccount.user_id == user_id)
    )

    total = int(
        (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one() or 0
    )
    dismissed = int(
        (
            await session.execute(
                select(func.count()).select_from(
                    base.where(UnsubscribeSuggestion.dismissed.is_(True)).subquery(),
                ),
            )
        ).scalar_one()
        or 0
    )
    avg_freq = (
        await session.execute(
            select(func.avg(UnsubscribeSuggestion.frequency_30d))
            .join(
                ConnectedAccount,
                ConnectedAccount.id == UnsubscribeSuggestion.account_id,
            )
            .where(
                ConnectedAccount.user_id == user_id,
                UnsubscribeSuggestion.dismissed.is_(False),
            ),
        )
    ).scalar_one_or_none()
    active = max(total - dismissed, 0)
    avg_freq_decimal = (
        Decimal(str(avg_freq)).quantize(Decimal("0.01"))
        if avg_freq is not None
        else Decimal("0.00")
    )

    domain_rows = (
        await session.execute(
            select(
                UnsubscribeSuggestion.sender_domain,
                func.sum(UnsubscribeSuggestion.frequency_30d).label("freq"),
                func.avg(UnsubscribeSuggestion.waste_rate).label("avg_waste"),
            )
            .join(
                ConnectedAccount,
                ConnectedAccount.id == UnsubscribeSuggestion.account_id,
            )
            .where(
                ConnectedAccount.user_id == user_id,
                UnsubscribeSuggestion.dismissed.is_(False),
            )
            .group_by(UnsubscribeSuggestion.sender_domain)
            .order_by(func.sum(UnsubscribeSuggestion.frequency_30d).desc())
            .limit(_TOP_DOMAIN_CAP),
        )
    ).all()

    top_domains = tuple(
        DomainWasteEntry(
            sender_domain=row.sender_domain,
            frequency_30d=int(row.freq or 0),
            waste_share=(
                Decimal(str(row.avg_waste)).quantize(Decimal("0.001"))
                if row.avg_waste is not None
                else Decimal("0.000")
            ),
        )
        for row in domain_rows
    )

    return HygieneStatsResponse(
        total_candidates=active,
        dismissed_count=dismissed,
        average_frequency=avg_freq_decimal,
        top_domains=top_domains,
    )


async def _load_owned(
    session: AsyncSession,
    *,
    suggestion_id: UUID,
    user_id: UUID,
) -> UnsubscribeSuggestion:
    """Return the suggestion row when the caller owns it, else 404.

    Args:
        session: Active async session.
        suggestion_id: Target primary key.
        user_id: Authenticated owner.

    Returns:
        The attached :class:`UnsubscribeSuggestion`.

    Raises:
        HTTPException: 404 when the row is absent or owned by someone
            else.
    """
    stmt = (
        select(UnsubscribeSuggestion)
        .join(
            ConnectedAccount,
            ConnectedAccount.id == UnsubscribeSuggestion.account_id,
        )
        .where(
            UnsubscribeSuggestion.id == suggestion_id,
            ConnectedAccount.user_id == user_id,
        )
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="suggestion not found")
    return row


def _action_from_json(value: object | None) -> UnsubscribeActionOut | None:
    """Rebuild :class:`UnsubscribeActionOut` from the stored JSON column.

    Args:
        value: Raw JSON dict from ``unsubscribe_suggestions.list_unsubscribe``
            (or ``None``).

    Returns:
        The boundary DTO, or ``None`` when nothing is stored.
    """
    if not isinstance(value, dict):
        return None
    http_urls = value.get("http_urls") or ()
    urls = tuple(str(url) for url in http_urls) if isinstance(http_urls, list | tuple) else ()
    mailto = value.get("mailto")
    return UnsubscribeActionOut(
        http_urls=urls,
        mailto=str(mailto) if mailto else None,
        one_click=bool(value.get("one_click", False)),
    )


# Module-level aliases so the v1 router mount picks up both.
router = unsubscribes_router
"""Primary router (``/unsubscribes``) kept for symmetry with other modules."""


__all__ = ["hygiene_router", "router", "unsubscribes_router"]
