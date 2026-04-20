"""SQLAlchemy 2.x ORM models for Phase 1 tables (plan §8).

Every model inherits from :class:`Base` and declares ``id``, ``created_at``,
``updated_at`` columns. Columns use the portable types in
:mod:`app.db.types` so the same ORM runs on Postgres (production) and
SQLite (unit tests).

Only Phase 1 tables live here today; later phases add
``classifications``, ``summaries``, ``job_matches``, etc.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.db.types import StringArray, citext_column, json_column

_ACCOUNT_STATUS_CHOICES = ("active", "disabled", "revoked")
"""Lifecycle states a connected account can be in."""

_USER_STATUS_CHOICES = ("active", "disabled", "deleted")


def _uuid_factory() -> uuid.UUID:
    """Default factory for ORM-generated UUID primary keys."""
    return uuid.uuid4()


class Base(DeclarativeBase):
    """Project-wide declarative base.

    Every ORM model extends this class. :attr:`metadata` is imported by
    :mod:`backend.alembic.env` so ``alembic revision --autogenerate``
    picks up schema drift.
    """


class TimestampMixin:
    """Mixin providing :attr:`created_at` and :attr:`updated_at` columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )


class User(Base, TimestampMixin):
    """Account owner (plan §8 ``users`` table).

    Attributes:
        id: Primary key (UUIDv4).
        email: Owner email — unique, case-insensitive.
        display_name: Optional display name.
        tz: IANA timezone string (defaults to UTC).
        status: Lifecycle state (one of ``_USER_STATUS_CHOICES``).
        last_login_at: UTC timestamp of the most recent login.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','disabled','deleted')",
            name="ck_users_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    email: Mapped[str] = mapped_column(citext_column(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    tz: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    accounts: Mapped[list[ConnectedAccount]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )


class ConnectedAccount(Base, TimestampMixin):
    """One row per (user, Gmail mailbox) (plan §8, §19.7).

    Attributes:
        id: Primary key.
        user_id: Owning user.
        provider: Always ``"gmail"`` in 1.0.0; reserved for OutlookProvider.
        email: Mailbox address.
        gmail_account_id: Google subject identifier (``sub``); locked at
            connect time so we detect account swaps.
        status: Lifecycle state (``active``/``disabled``/``revoked``).
        daily_budget_in: Max input tokens/day the pipeline may spend here.
        daily_budget_out: Max output tokens/day.
        exclude_from_global_digest: Plan §19.7 — per-mailbox opt-out.
        auto_scan_enabled: Plan §20.2 tri-state; ``True`` by default.
    """

    __tablename__ = "connected_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "email", name="uq_connected_accounts_user_email"),
        CheckConstraint("provider = 'gmail'", name="ck_connected_accounts_provider"),
        CheckConstraint(
            "status IN ('active','disabled','revoked')",
            name="ck_connected_accounts_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="gmail")
    email: Mapped[str] = mapped_column(citext_column(320), nullable=False)
    gmail_account_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    daily_budget_in: Mapped[int] = mapped_column(Integer, nullable=False, default=500_000)
    daily_budget_out: Mapped[int] = mapped_column(Integer, nullable=False, default=100_000)
    exclude_from_global_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_scan_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    owner: Mapped[User] = relationship(back_populates="accounts")
    tokens: Mapped[OAuthToken | None] = relationship(
        back_populates="account",
        uselist=False,
        cascade="all, delete-orphan",
    )
    cursor: Mapped[SyncCursor | None] = relationship(
        back_populates="account",
        uselist=False,
        cascade="all, delete-orphan",
    )
    emails: Mapped[list[Email]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
    )


class OAuthToken(Base, TimestampMixin):
    """Envelope-encrypted OAuth credentials (plan §8, §20.3).

    Attributes:
        id: Primary key.
        account_id: Owning connected account (1:1).
        access_token_ct: Envelope ciphertext over the access token.
        refresh_token_ct: Envelope ciphertext over the refresh token.
        scope: Raw granted scope strings.
        expires_at: UTC expiry of the access token.
    """

    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    access_token_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scope: Mapped[list[str]] = mapped_column(StringArray(), nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped[ConnectedAccount] = relationship(back_populates="tokens")


class SyncCursor(Base, TimestampMixin):
    """Incremental-sync cursor per account (plan §8).

    Attributes:
        account_id: Primary key + FK to connected_accounts.
        history_id: Latest provider historyId.
        last_full_sync_at: UTC timestamp of the last bounded full sync.
        last_incremental_at: UTC timestamp of the last incremental run.
        stale: True when the provider rejected this cursor (bounded
            re-sync must run next).
    """

    __tablename__ = "sync_cursors"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    history_id: Mapped[int | None] = mapped_column(Integer)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_incremental_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    account: Mapped[ConnectedAccount] = relationship(back_populates="cursor")


class Email(Base, TimestampMixin):
    """Email metadata row (plan §8, §19.7 body split).

    Bodies live in :class:`EmailContentBlob`; this table stays index-hot
    and small.

    Attributes:
        id: Primary key.
        account_id: Owning connected account.
        gmail_message_id: Provider-scoped message id.
        thread_id: Provider-scoped thread id.
        internal_date: Provider-reported send time (UTC).
        from_addr: Raw ``From`` address.
        to_addrs: Raw ``To`` recipients.
        cc_addrs: Raw ``Cc`` recipients.
        subject: Decoded subject.
        snippet: Provider-supplied preview text.
        labels: Provider labels/folders.
        list_unsubscribe: Normalised ``List-Unsubscribe`` (JSON).
        content_hash: SHA-256 over subject+from+internal_date+snippet.
        size_bytes: Declared MIME size.
        raw_s3_key: Deprecated — body storage moved to
            :class:`EmailContentBlob` but the column survives for a
            migration window per §19.7.
    """

    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "gmail_message_id",
            name="uq_emails_account_message",
        ),
        Index("ix_emails_account_internal_date", "account_id", "internal_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connected_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    gmail_message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    internal_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    from_addr: Mapped[str] = mapped_column(citext_column(320), nullable=False)
    to_addrs: Mapped[list[str]] = mapped_column(StringArray(), nullable=False, default=list)
    cc_addrs: Mapped[list[str]] = mapped_column(StringArray(), nullable=False, default=list)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    labels: Mapped[list[str]] = mapped_column(StringArray(), nullable=False, default=list)
    list_unsubscribe: Mapped[Any | None] = mapped_column(json_column())
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_s3_key: Mapped[str | None] = mapped_column(Text)

    account: Mapped[ConnectedAccount] = relationship(back_populates="emails")
    body: Mapped[EmailContentBlob | None] = relationship(
        back_populates="email",
        uselist=False,
        cascade="all, delete-orphan",
    )


class EmailContentBlob(Base, TimestampMixin):
    """Out-of-row body for an email (plan §19.7).

    Attributes:
        id: Primary key.
        message_id: Owning email (1:1).
        storage_backend: Either ``"pg"`` (excerpt in-row) or ``"s3"``
            (excerpt elided, full body in S3).
        object_key: S3 object key when ``storage_backend='s3'``.
        plain_text_excerpt: First N chars of decoded text/plain.
        html_sanitized_key: Optional S3 key for the sanitized HTML.
        quoted_text_removed: True when the parser trimmed a reply tail.
        language: Detected language code.
        size_bytes: Raw body size before excerpting.
    """

    __tablename__ = "email_content_blobs"
    __table_args__ = (
        CheckConstraint(
            "storage_backend IN ('pg','s3')",
            name="ck_email_content_blobs_storage",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    storage_backend: Mapped[str] = mapped_column(String(8), nullable=False, default="pg")
    object_key: Mapped[str | None] = mapped_column(Text)
    plain_text_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    html_sanitized_key: Mapped[str | None] = mapped_column(Text)
    quoted_text_removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    language: Mapped[str | None] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    email: Mapped[Email] = relationship(back_populates="body")


__all__ = [
    "Base",
    "ConnectedAccount",
    "Email",
    "EmailContentBlob",
    "OAuthToken",
    "SyncCursor",
    "TimestampMixin",
    "User",
]
