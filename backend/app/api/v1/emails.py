"""``/api/v1/emails`` router for bucket lists and user overrides."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, or_, select

from app.api.deps import current_user_id, db_session
from app.api.errors import api_error_response
from app.core.app_config import get_app_config
from app.core.config import Settings, get_settings
from app.core.consent import enforce_legal_consent
from app.core.errors import CryptoError, ProviderError, QuotaExceededError
from app.core.security import EncryptedBlob, EnvelopeCipher, token_context
from app.db.models import Classification, ConnectedAccount, Email, OAuthToken, Summary, User
from app.domain.providers import ProviderCredentials
from app.schemas.emails import (
    DecisionSource,
    EmailBucket,
    EmailBucketPatchRequest,
    EmailRowOut,
    EmailsListResponse,
    ErrorEnvelope,
    MarkReadFailureOut,
    MarkReadRequest,
    MarkReadResponse,
)
from app.schemas.legal import LegalConsentRequiredError
from app.services.classification.repository import ClassificationsRepo, ClassificationWrite
from app.services.email_labels import drop_unread_label, unread_email_filter
from app.services.gmail.client import GmailClient
from app.services.gmail.oauth import (
    expires_at_from_bundle,
    has_gmail_modify_scope,
    refresh_access_token,
)
from app.services.gmail.provider import GmailProvider
from app.services.summarization.repository import SummariesRepo

if TYPE_CHECKING:  # pragma: no cover
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import KmsClient
    from app.domain.providers import MailboxProvider


router = APIRouter(prefix="/emails", tags=["emails"])
_APP_CONFIG = get_app_config()

_PRIMARY_BUCKETS: tuple[EmailBucket, ...] = cast(
    tuple[EmailBucket, ...],
    _APP_CONFIG.taxonomy.user_facing_buckets,
)
"""Buckets the PWA renders as email lists."""
_EMAILS_DEFAULT_LIMIT = _APP_CONFIG.api.emails_default_limit
_EMAILS_MAX_LIMIT = _APP_CONFIG.api.emails_max_limit
_TOKEN_REFRESH_LEEWAY = timedelta(minutes=5)
"""Refresh Gmail access tokens before they expire inside a mark-read call."""


class MarkReadApiError(Exception):
    """Endpoint-local error converted to an Aegis response envelope.

    Attributes:
        status_code: HTTP status code returned to the client.
        code: Stable machine-readable error code.
        message: Human-readable error summary.
        details: Structured diagnostic context.
    """

    status_code: int
    code: str
    message: str
    details: dict[str, object]

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """Capture one mark-read API error.

        Args:
            status_code: HTTP status code returned to the client.
            code: Stable machine-readable error code.
            message: Human-readable error summary.
            details: Structured diagnostic context.
        """
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def _classifications_repo_for(settings: Settings) -> ClassificationsRepo:
    """Return a classification repo wired to KMS when configured."""
    if not settings.content_key_alias:
        return ClassificationsRepo(cipher=None)
    import boto3  # type: ignore[import-untyped]

    from app.core.security import EnvelopeCipher

    return ClassificationsRepo(
        cipher=EnvelopeCipher(
            key_id=settings.content_key_alias,
            client=cast("KmsClient", boto3.client("kms")),
        ),
    )


def _summaries_repo_for(settings: Settings) -> SummariesRepo:
    """Return a summaries repo wired to KMS when configured."""
    if not settings.content_key_alias:
        return SummariesRepo(cipher=None)
    import boto3

    from app.core.security import EnvelopeCipher

    return SummariesRepo(
        cipher=EnvelopeCipher(
            key_id=settings.content_key_alias,
            client=cast("KmsClient", boto3.client("kms")),
        ),
    )


@router.get("", response_model=EmailsListResponse, summary="List classified emails")
async def list_emails(
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
    bucket: EmailBucket | None = Query(default=None),
    account_id: UUID | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=200),
    sender: str | None = Query(default=None, min_length=1, max_length=320),
    received_after: datetime | None = Query(default=None),
    received_before: datetime | None = Query(default=None),
    has_summary: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=_EMAILS_DEFAULT_LIMIT, ge=1, le=_EMAILS_MAX_LIMIT),
) -> EmailsListResponse:
    """Return classified email rows for the PWA.

    Args:
        user_id: Authenticated owner.
        session: Active async session.
        settings: Cached app settings.
        bucket: Optional primary bucket filter.
        account_id: Optional account filter.
        q: Optional case-insensitive subject/sender search.
        sender: Optional exact sender filter.
        received_after: Optional lower bound for provider received time.
        received_before: Optional upper bound for provider received time.
        has_summary: Optional filter for rows with or without email summaries.
        offset: Result offset for pagination.
        limit: Maximum row count.

    Returns:
        Newest-first rows plus total count.
    """
    base_filters = [
        ConnectedAccount.user_id == user_id,
        Classification.label.in_(_PRIMARY_BUCKETS),
        unread_email_filter(session),
    ]
    if bucket is not None:
        base_filters.append(Classification.label == bucket)
    if account_id is not None:
        base_filters.append(ConnectedAccount.id == account_id)
    if q is not None:
        needle = f"%{q.strip().lower()}%"
        base_filters.append(
            or_(
                func.lower(Email.subject).like(needle),
                func.lower(Email.from_addr).like(needle),
            ),
        )
    if sender is not None:
        base_filters.append(func.lower(Email.from_addr) == sender.strip().lower())
    if received_after is not None:
        base_filters.append(Email.internal_date >= received_after)
    if received_before is not None:
        base_filters.append(Email.internal_date <= received_before)
    if has_summary is True:
        base_filters.append(Summary.id.is_not(None))
    if has_summary is False:
        base_filters.append(Summary.id.is_(None))

    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Email)
                .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
                .join(Classification, Classification.email_id == Email.id)
                .outerjoin(
                    Summary,
                    and_(Summary.email_id == Email.id, Summary.kind == "email"),
                )
                .where(*base_filters),
            )
        ).scalar_one()
        or 0
    )

    rows = (
        await session.execute(
            select(Email, ConnectedAccount, Classification, Summary)
            .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
            .join(Classification, Classification.email_id == Email.id)
            .outerjoin(
                Summary,
                and_(Summary.email_id == Email.id, Summary.kind == "email"),
            )
            .where(*base_filters)
            .order_by(Email.internal_date.desc())
            .offset(offset)
            .limit(limit),
        )
    ).all()

    classification_repo = _classifications_repo_for(settings)
    summary_repo = _summaries_repo_for(settings)
    return EmailsListResponse(
        emails=tuple(
            _row_out(
                email=email,
                account=account,
                classification=classification,
                summary=summary,
                user_id=user_id,
                classification_repo=classification_repo,
                summary_repo=summary_repo,
            )
            for email, account, classification, summary in rows
        ),
        total=total,
    )


@router.post(
    "/mark-read",
    response_model=MarkReadResponse,
    summary="Mark emails read in Gmail",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_409_CONFLICT: {"model": ErrorEnvelope},
        status.HTTP_451_UNAVAILABLE_FOR_LEGAL_REASONS: {
            "model": LegalConsentRequiredError,
            "description": "Current legal consent is required before Gmail processing.",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorEnvelope},
    },
)
async def mark_read_emails(
    body: MarkReadRequest,
    request: Request,
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> MarkReadResponse | JSONResponse:
    """Remove ``UNREAD`` from selected Gmail messages and local labels.

    Args:
        body: Explicit email ids or a category selector.
        request: Incoming request, used for error correlation.
        user_id: Authenticated owner.
        session: Active async session.
        settings: Cached app settings.

    Returns:
        Count of successfully processed messages and per-email failures.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    enforce_legal_consent(user)

    try:
        if body.account_id is not None:
            await _ensure_account_owned(
                session=session,
                user_id=user_id,
                account_id=body.account_id,
            )

        rows = await _mark_read_targets(session=session, user_id=user_id, body=body)
        if body.email_ids and len(rows) != len(body.email_ids):
            raise MarkReadApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="email_not_found",
                message="Email not found.",
                details={"selector": "email_ids"},
            )
        if not rows:
            return MarkReadResponse(marked=0)

        grouped = _targets_by_account(rows)
        cipher = _token_cipher_for(settings)
        import httpx

        async with httpx.AsyncClient() as http_client:
            provider = _gmail_provider_for(http_client=http_client)
            credentials_by_account: dict[UUID, ProviderCredentials] = {}
            for account_id in grouped:
                credentials_by_account[account_id] = await _credentials_for_mark_read(
                    session=session,
                    account_id=account_id,
                    settings=settings,
                    cipher=cipher,
                    http_client=http_client,
                )
            try:
                response = await _mark_read_grouped(
                    grouped=grouped,
                    credentials_by_account=credentials_by_account,
                    provider=provider,
                )
            except (ProviderError, QuotaExceededError) as exc:
                raise MarkReadApiError(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    code="gmail_mark_read_unavailable",
                    message="Gmail mark-read is unavailable.",
                    details={"provider": "gmail"},
                ) from exc

        await session.flush()
        return response
    except MarkReadApiError as exc:
        return _mark_read_error_response(error=exc, request=request)


@router.patch(
    "/{email_id}/bucket",
    response_model=EmailRowOut,
    summary="Update a user-selected email bucket",
)
async def patch_email_bucket(
    email_id: UUID,
    body: EmailBucketPatchRequest,
    *,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> EmailRowOut:
    """Persist a user override from swipe gestures or queued replay.

    Args:
        email_id: Target email.
        body: Destination bucket.
        user_id: Authenticated owner.
        session: Active async session.
        settings: Cached app settings.

    Returns:
        Updated email row.

    Raises:
        HTTPException: 404 when the email does not belong to the caller.
    """
    owned = (
        await session.execute(
            select(Email, ConnectedAccount, Classification, Summary)
            .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
            .outerjoin(Classification, Classification.email_id == Email.id)
            .outerjoin(
                Summary,
                and_(Summary.email_id == Email.id, Summary.kind == "email"),
            )
            .where(Email.id == email_id, ConnectedAccount.user_id == user_id),
        )
    ).first()
    if owned is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="email not found")

    email, account, _classification, summary = owned
    classification_repo = _classifications_repo_for(settings)
    await classification_repo.upsert(
        session,
        ClassificationWrite(
            email_id=email.id,
            label=body.bucket,
            score=Decimal("1.000"),
            rubric_version=0,
            prompt_version_id=None,
            decision_source="rule",
            model="user_override",
            tokens_in=0,
            tokens_out=0,
            is_newsletter=False,
            reasons={"reasons": ["User moved this email in the PWA."]},
            user_id=user_id,
            needs_review=False,
        ),
    )
    classification = (
        (
            await session.execute(
                select(Classification).where(Classification.email_id == email.id),
            )
        )
        .scalars()
        .one()
    )
    return _row_out(
        email=email,
        account=account,
        classification=classification,
        summary=summary,
        user_id=user_id,
        classification_repo=classification_repo,
        summary_repo=_summaries_repo_for(settings),
    )


async def _ensure_account_owned(
    *,
    session: AsyncSession,
    user_id: UUID,
    account_id: UUID,
) -> None:
    """Raise 404 if a connected account is not owned by the caller.

    Args:
        session: Active async session.
        user_id: Authenticated owner.
        account_id: Connected account id from the request.

    Raises:
        MarkReadApiError: 404 when the account is absent or owned by another
            user.
    """
    owned = (
        await session.execute(
            select(ConnectedAccount.id).where(
                ConnectedAccount.id == account_id,
                ConnectedAccount.user_id == user_id,
            ),
        )
    ).scalar_one_or_none()
    if owned is None:
        raise MarkReadApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="account_not_found",
            message="Account not found.",
            details={"accountId": str(account_id)},
        )


async def _mark_read_targets(
    *,
    session: AsyncSession,
    user_id: UUID,
    body: MarkReadRequest,
) -> list[tuple[Email, ConnectedAccount]]:
    """Load emails selected for mark-read.

    Args:
        session: Active async session.
        user_id: Authenticated owner.
        body: Validated mark-read request.

    Returns:
        Owned ``(Email, ConnectedAccount)`` pairs.
    """
    stmt = (
        select(Email, ConnectedAccount)
        .join(ConnectedAccount, ConnectedAccount.id == Email.account_id)
        .where(ConnectedAccount.user_id == user_id)
        .order_by(Email.internal_date.desc(), Email.id.desc())
    )
    if body.account_id is not None:
        stmt = stmt.where(Email.account_id == body.account_id)
    if body.email_ids:
        stmt = stmt.where(Email.id.in_(body.email_ids))
    else:
        stmt = (
            stmt.join(Classification, Classification.email_id == Email.id)
            .where(Classification.label == body.category)
            .where(unread_email_filter(session))
        )
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


def _targets_by_account(
    rows: list[tuple[Email, ConnectedAccount]],
) -> dict[UUID, list[tuple[Email, ConnectedAccount]]]:
    """Group mark-read targets by connected account.

    Args:
        rows: Owned email/account pairs.

    Returns:
        Mapping of account id to targets for that account.
    """
    grouped: dict[UUID, list[tuple[Email, ConnectedAccount]]] = {}
    for email, account in rows:
        grouped.setdefault(account.id, []).append((email, account))
    return grouped


async def _mark_read_grouped(
    *,
    grouped: dict[UUID, list[tuple[Email, ConnectedAccount]]],
    credentials_by_account: dict[UUID, ProviderCredentials],
    provider: MailboxProvider,
) -> MarkReadResponse:
    """Call the provider per account and update local labels for successes.

    Args:
        grouped: Account-scoped mark-read targets.
        credentials_by_account: Decrypted credentials per account.
        provider: Mailbox provider implementation.

    Returns:
        API response with local success count and failures.
    """
    marked = 0
    failures: list[MarkReadFailureOut] = []
    for account_id, rows in grouped.items():
        result = await provider.mark_read(
            credentials_by_account[account_id],
            [email.gmail_message_id for email, _account in rows],
        )
        marked_ids = set(result.marked)
        failed_by_message = {failure.message_id: failure.reason for failure in result.failed}
        for email, _account in rows:
            if email.gmail_message_id in marked_ids:
                email.labels = drop_unread_label(email.labels)
                marked += 1
                continue
            reason = failed_by_message.get(email.gmail_message_id)
            if reason is not None:
                failures.append(
                    MarkReadFailureOut(
                        email_id=email.id,
                        provider_message_id=email.gmail_message_id,
                        reason=reason,
                    ),
                )
    return MarkReadResponse(marked=marked, failed=tuple(failures))


async def _credentials_for_mark_read(
    *,
    session: AsyncSession,
    account_id: UUID,
    settings: Settings,
    cipher: EnvelopeCipher,
    http_client: httpx.AsyncClient,
) -> ProviderCredentials:
    """Return decrypted Gmail credentials for mark-read.

    Args:
        session: Active async session.
        account_id: Connected account id.
        settings: Cached app settings.
        cipher: Token-wrap envelope cipher.
        http_client: Shared HTTP client for token refresh.

    Returns:
        Decrypted OAuth credentials.

    Raises:
        MarkReadApiError: 409 when the account has not re-consented to
            ``gmail.modify``; 503 when token unwrap/refresh is unavailable.
    """
    tokens = (
        (
            await session.execute(
                select(OAuthToken).where(OAuthToken.account_id == account_id),
            )
        )
        .scalars()
        .first()
    )
    if tokens is None or not has_gmail_modify_scope(tuple(tokens.scope)):
        raise _reauthorize_error(account_id=account_id)

    account_ctx = str(account_id)
    try:
        access_plain = cipher.decrypt(
            _blob(tokens.access_token_ct),
            token_context(account_id=account_ctx, purpose="access_token"),
        ).decode("utf-8")
        refresh_plain = cipher.decrypt(
            _blob(tokens.refresh_token_ct),
            token_context(account_id=account_ctx, purpose="refresh_token"),
        ).decode("utf-8")
    except CryptoError as exc:
        raise MarkReadApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="token_decryption_unavailable",
            message="Token decryption is unavailable.",
            details={"accountId": str(account_id)},
        ) from exc

    if _expires_within(tokens.expires_at, _TOKEN_REFRESH_LEEWAY):
        if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
            raise MarkReadApiError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="google_oauth_refresh_unavailable",
                message="Google OAuth client credentials are required to refresh Gmail token.",
                details={"accountId": str(account_id)},
            )
        bundle = await refresh_access_token(
            refresh_token=refresh_plain,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            http_client=http_client,
        )
        refreshed_scope = tuple(bundle.scope.split())
        if refreshed_scope and not has_gmail_modify_scope(refreshed_scope):
            raise _reauthorize_error(account_id=account_id)
        access_plain = bundle.access_token
        try:
            access_blob = cipher.encrypt(
                access_plain.encode("utf-8"),
                token_context(account_id=account_ctx, purpose="access_token"),
            )
            tokens.access_token_ct = access_blob.ciphertext
            if bundle.refresh_token:
                refresh_plain = bundle.refresh_token
                refresh_blob = cipher.encrypt(
                    refresh_plain.encode("utf-8"),
                    token_context(account_id=account_ctx, purpose="refresh_token"),
                )
                tokens.refresh_token_ct = refresh_blob.ciphertext
        except CryptoError as exc:
            raise MarkReadApiError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="token_encryption_unavailable",
                message="Token encryption is unavailable.",
                details={"accountId": str(account_id)},
            ) from exc
        if refreshed_scope:
            tokens.scope = list(refreshed_scope)
        tokens.expires_at = expires_at_from_bundle(bundle)
        await session.flush()

    return ProviderCredentials(
        account_id=account_id,
        access_token=access_plain,
        refresh_token=refresh_plain,
        scope=tuple(tokens.scope),
        expires_at=tokens.expires_at,
    )


def _token_cipher_for(settings: Settings) -> EnvelopeCipher:
    """Construct the token-wrap cipher for OAuth token unwrap.

    Args:
        settings: Cached application settings.

    Returns:
        A ready-to-use envelope cipher.

    Raises:
        MarkReadApiError: 503 when the KMS alias is unavailable.
    """
    alias = settings.token_wrap_key_alias
    if not alias:
        raise MarkReadApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="token_wrap_unavailable",
            message="KMS token-wrap alias is not configured.",
        )
    import boto3

    return EnvelopeCipher(key_id=alias, client=cast("KmsClient", boto3.client("kms")))


def _gmail_provider_for(*, http_client: httpx.AsyncClient) -> MailboxProvider:
    """Return the Gmail mailbox provider used by the mark-read endpoint.

    Args:
        http_client: Shared HTTP client for Gmail calls.

    Returns:
        Mailbox provider implementation.
    """
    return GmailProvider(
        client=GmailClient(http_client=http_client),
        http_client=http_client,
    )


def _blob(ciphertext: bytes) -> EncryptedBlob:
    """Coerce raw token ciphertext into an :class:`EncryptedBlob`.

    Args:
        ciphertext: Raw DB ``BYTEA`` value.

    Returns:
        Envelope ciphertext wrapper.
    """
    return EncryptedBlob(ciphertext=bytes(ciphertext))


def _expires_within(expires_at: datetime, leeway: timedelta) -> bool:
    """Return True when ``expires_at`` is already expired or nearly expired.

    Args:
        expires_at: OAuth access-token expiry.
        leeway: Refresh window.

    Returns:
        True when refresh should occur before a Gmail call.
    """
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(tz=UTC) + leeway


def _reauthorize_error(*, account_id: UUID) -> MarkReadApiError:
    """Return a clear re-consent error for accounts missing Gmail modify.

    Args:
        account_id: Connected account missing ``gmail.modify``.

    Returns:
        API error instructing the client to reconnect Gmail.
    """
    return MarkReadApiError(
        status_code=status.HTTP_409_CONFLICT,
        code="gmail_reauthorization_required",
        message="Gmail re-authorization is required before mark-read.",
        details={"accountId": str(account_id), "scope": "gmail.modify"},
    )


def _mark_read_error_response(*, error: MarkReadApiError, request: Request) -> JSONResponse:
    """Convert a mark-read error to the Aegis response envelope.

    Args:
        error: Endpoint-local API error.
        request: Incoming request, used for error correlation.

    Returns:
        JSON response with top-level ``code``, ``message``, ``details``,
        and ``requestId`` fields.
    """
    return api_error_response(
        status_code=error.status_code,
        code=error.code,
        message=error.message,
        details=error.details,
        request=request,
    )


def _row_out(
    *,
    email: Email,
    account: ConnectedAccount,
    classification: Classification,
    summary: Summary | None,
    user_id: UUID,
    classification_repo: ClassificationsRepo,
    summary_repo: SummariesRepo,
) -> EmailRowOut:
    """Convert ORM rows to the frontend email-row contract."""
    return EmailRowOut(
        id=email.id,
        account_email=account.email,
        thread_id=email.thread_id,
        subject=email.subject,
        sender=email.from_addr,
        received_at=email.internal_date,
        bucket=cast(EmailBucket, classification.label),
        confidence=float(classification.score),
        needs_review=classification.needs_review,
        decision_source=_decision_source(classification.decision_source),
        reasons=_reasons_from(
            classification_repo.decrypt_reasons(row=classification, user_id=user_id),
        ),
        summary_excerpt=_summary_excerpt(summary=summary, user_id=user_id, repo=summary_repo),
    )


def _decision_source(source: str) -> DecisionSource:
    """Map persisted source names onto frontend vocabulary."""
    if source == "model":
        return "llm"
    if source == "hybrid":
        return "hybrid"
    return "rule"


def _reasons_from(payload: dict[str, Any]) -> tuple[str, ...]:
    """Extract displayable reasons from a decrypted rationale payload."""
    for key in ("reasons", "reason", "rationale", "rationale_short"):
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(str(item) for item in value if str(item).strip())
        if isinstance(value, str) and value.strip():
            return (value.strip(),)
    return ("No rationale captured.",)


def _summary_excerpt(
    *,
    summary: Summary | None,
    user_id: UUID,
    repo: SummariesRepo,
) -> str | None:
    """Return a short plaintext summary preview when one exists."""
    if summary is None:
        return None
    body = repo.decrypt_email_body(row=summary, user_id=user_id).replace("\n", " ").strip()
    if not body:
        return None
    return body if len(body) <= 180 else f"{body[:177]}..."
