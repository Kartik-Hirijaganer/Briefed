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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.api.deps import current_user_id, db_session
from app.api.errors import api_error_response
from app.core.app_config import get_app_config
from app.core.clock import utcnow
from app.core.config import Settings, get_settings
from app.core.consent import enforce_legal_consent
from app.db.models import ConnectedAccount, UnsubscribeSuggestion, User
from app.schemas.emails import ErrorEnvelope
from app.schemas.legal import LegalConsentRequiredError
from app.schemas.unsubscribe import (
    DomainWasteEntry,
    HygieneStatsResponse,
    UnsubscribeActionOut,
    UnsubscribeExecuteRequest,
    UnsubscribeExecuteResponse,
    UnsubscribeSuggestionOut,
    UnsubscribeSuggestionsListResponse,
)
from app.services.unsubscribe.executor import execute_unsubscribe
from app.services.unsubscribe.parser import UnsubscribeAction
from app.services.unsubscribe.repository import UnsubscribeSuggestionsRepo

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import KmsClient


unsubscribes_router = APIRouter(prefix="/unsubscribes", tags=["unsubscribes"])
hygiene_router = APIRouter(prefix="/hygiene", tags=["hygiene"])
_APP_CONFIG = get_app_config()

_TOP_DOMAIN_CAP = _APP_CONFIG.api.top_domain_cap
"""Plan §14 Phase 5 — dashboard card shows at most 10 top domains."""

_RECOMMENDATION_CONFIDENCE_MIN = _APP_CONFIG.api.unsubscribe_recommendation_confidence_min
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
            recent_subjects=tuple(row.recent_subjects),
        )
        for row in rows
    )
    return UnsubscribeSuggestionsListResponse(suggestions=suggestions)


@unsubscribes_router.post(
    "/{suggestion_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dismiss an unsubscribe suggestion",
    responses={
        status.HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS: {
            "model": LegalConsentRequiredError,
            "description": "Current legal consent is required before Gmail-derived state changes.",
        },
    },
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
    await _enforce_current_consent(session=session, user_id=user_id)
    row = await _load_owned(session, suggestion_id=suggestion_id, user_id=user_id)
    row.dismissed = True
    row.dismissed_at = utcnow()
    await session.flush()


@unsubscribes_router.post(
    "/{suggestion_id}/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirm the user acted on the unsubscribe suggestion",
    responses={
        status.HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS: {
            "model": LegalConsentRequiredError,
            "description": "Current legal consent is required before Gmail-derived state changes.",
        },
    },
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
    await _enforce_current_consent(session=session, user_id=user_id)
    row = await _load_owned(session, suggestion_id=suggestion_id, user_id=user_id)
    row.dismissed = True
    row.dismissed_at = utcnow()
    await session.flush()


@unsubscribes_router.post(
    "/{suggestion_id}/execute",
    response_model=UnsubscribeExecuteResponse,
    summary="Execute an unsubscribe (ADR 0014, gated)",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorEnvelope},
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS: {
            "model": LegalConsentRequiredError,
            "description": "Current legal consent is required before Gmail-derived state changes.",
        },
    },
)
async def execute_suggestion(
    suggestion_id: UUID,
    body: UnsubscribeExecuteRequest,
    request: Request,
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> UnsubscribeExecuteResponse | JSONResponse:
    """Execute (or surface) the sender-advertised unsubscribe for a row.

    Gated behind ``FeatureConfig.unsubscribe_execute`` (ADR 0014): when the
    flag is off the endpoint 404s so the capability stays invisible. Requires
    an explicit ``{"confirm": true}`` body. Re-executing an already
    ``unsubscribed`` row is a no-op. On a successful one-click the row is also
    dismissed so it drops from the active list; ``manual_required`` / ``failed``
    rows stay active.

    Args:
        suggestion_id: Target suggestion.
        body: Confirmation envelope.
        request: Incoming request, used for error correlation.
        user_id: Authenticated owner.
        session: Active async session.
        settings: Cached :class:`Settings`.

    Returns:
        :class:`UnsubscribeExecuteResponse` describing the outcome.

    Raises:
        Aegis-compatible error response when the flag is off, the row is not
        owned, or ``confirm`` is not true.
    """
    if not _APP_CONFIG.features.unsubscribe_execute:
        return api_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
            message="not found",
            request=request,
        )
    if not body.confirm:
        return api_error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsubscribe_confirmation_required",
            message="Explicit confirmation is required to execute an unsubscribe.",
            request=request,
        )

    await _enforce_current_consent(session=session, user_id=user_id)

    row = await _find_owned(session, suggestion_id=suggestion_id, user_id=user_id)
    if row is None:
        return api_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
            message="suggestion not found",
            request=request,
        )
    if row.execute_status == "unsubscribed":
        # Idempotent: never re-POST an already-completed unsubscribe.
        existing_via: Literal["one_click", "none"] = (
            "one_click" if row.executed_via == "one_click" else "none"
        )
        return UnsubscribeExecuteResponse(
            status="unsubscribed",
            executed_via=existing_via,
            manual_url=None,
            message="Already unsubscribed.",
        )

    action_out = _action_from_json(row.list_unsubscribe)
    action = (
        UnsubscribeAction(
            http_urls=action_out.http_urls,
            mailto=action_out.mailto,
            one_click=action_out.one_click,
        )
        if action_out is not None
        else UnsubscribeAction()
    )

    import httpx  # deferred import keeps module load SnapStart-friendly

    # trust_env=False ignores proxy env vars; follow_redirects=False stops a
    # 3xx-to-internal SSRF bypass (ADR 0014).
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as http_client:
        outcome = await execute_unsubscribe(
            action,
            http_client=http_client,
            timeout=settings.unsubscribe_execute_timeout_seconds,
        )

    now = utcnow()
    row.execute_attempted_at = now
    row.execute_status = outcome.status
    row.executed_via = outcome.executed_via
    row.execute_error = outcome.error
    row.manual_url = outcome.manual_url
    if outcome.status == "unsubscribed":
        row.executed_at = now
        row.dismissed = True
        row.dismissed_at = now
    await session.flush()

    return UnsubscribeExecuteResponse(
        status=outcome.status,
        executed_via=outcome.executed_via,
        manual_url=outcome.manual_url,
        message=outcome.message,
    )


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


async def _enforce_current_consent(*, session: AsyncSession, user_id: UUID) -> None:
    """Require current legal consent before Gmail-affecting mutations.

    Args:
        session: Active async session.
        user_id: Authenticated owner.

    Raises:
        HTTPException: 404 when the user row is missing, or 451 when legal
            consent is absent or stale.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    enforce_legal_consent(user)


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
    row = await _find_owned(session, suggestion_id=suggestion_id, user_id=user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="suggestion not found")
    return row


async def _find_owned(
    session: AsyncSession,
    *,
    suggestion_id: UUID,
    user_id: UUID,
) -> UnsubscribeSuggestion | None:
    """Return the suggestion row when the caller owns it, else ``None``.

    Args:
        session: Active async session.
        suggestion_id: Target primary key.
        user_id: Authenticated owner.

    Returns:
        The attached :class:`UnsubscribeSuggestion`, or ``None`` when absent or
        owned by another user.
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
