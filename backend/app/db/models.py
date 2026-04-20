"""SQLAlchemy 2.x ORM models for Phase 1 + Phase 2 tables (plan §8).

Every model inherits from :class:`Base` and declares ``id``, ``created_at``,
``updated_at`` columns. Columns use the portable types in
:mod:`app.db.types` so the same ORM runs on Postgres (production) and
SQLite (unit tests).

Phase 1 tables: ``users``, ``connected_accounts``, ``oauth_tokens``,
``sync_cursors``, ``emails``, ``email_content_blobs``.

Phase 2 tables (plan §14 Phase 2 + §20.10): ``classifications``,
``rubric_rules``, ``prompt_versions``, ``prompt_call_log``,
``known_waste_senders``.

Phase 3 tables (plan §14 Phase 3 + §20.10): ``summaries``,
``known_newsletters``, ``tech_news_clusters``. Later phases add
``job_matches``, ``unsubscribe_suggestions``, etc.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
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


_CLASSIFICATION_LABELS = (
    "must_read",
    "good_to_read",
    "ignore",
    "waste",
    "newsletter",
    "job_candidate",
    "needs_review",
)
"""Allowed triage labels persisted on ``classifications.label``."""

_DECISION_SOURCES = ("rule", "model", "hybrid")
"""Allowed values for ``classifications.decision_source`` (plan §19.7)."""

_PROMPT_CALL_STATUSES = ("ok", "fallback", "error", "skipped")
"""Allowed values for ``prompt_call_log.status``."""


class Classification(Base, TimestampMixin):
    """Per-email triage verdict (plan §8, §19.7, §20.10).

    ``reasons_ct`` + ``reasons_dek_wrapped`` hold the
    envelope-encrypted LLM rationale. The plaintext never lives on disk —
    ``ClassificationsRepo`` encrypts on write and decrypts on read via
    :mod:`app.core.content_crypto` so Supabase sees metadata only
    (label + score + timing) and never the rationale text.

    Attributes:
        id: Primary key.
        email_id: Target email (1:1).
        label: One of ``_CLASSIFICATION_LABELS``.
        score: Probability-calibrated confidence in ``[0, 1]``.
        rubric_version: ``rubric_rules.version`` that produced this row.
        prompt_version_id: FK into :class:`PromptVersion`; ``None`` when
            the rule engine short-circuited without an LLM call.
        decision_source: ``rule`` / ``model`` / ``hybrid``.
        model: Provider-scoped model identifier (e.g.
            ``gemini-1.5-flash``).
        tokens_in: Input tokens billed by the LLM (0 when rule-only).
        tokens_out: Output tokens billed.
        reasons_ct: Envelope ciphertext over the JSON reasons payload.
        reasons_dek_wrapped: Kept as ``None`` — the packed envelope blob
            already carries the wrapped DEK. Column reserved for a future
            split-storage layout; see plan §20.10.
    """

    __tablename__ = "classifications"
    __table_args__ = (
        CheckConstraint(
            "label IN ("
            "'must_read','good_to_read','ignore','waste',"
            "'newsletter','job_candidate','needs_review'"
            ")",
            name="ck_classifications_label",
        ),
        CheckConstraint(
            "decision_source IN ('rule','model','hybrid')",
            name="ck_classifications_decision_source",
        ),
        CheckConstraint(
            "score >= 0 AND score <= 1",
            name="ck_classifications_score_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    label: Mapped[str] = mapped_column(String(24), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
    )
    decision_source: Mapped[str] = mapped_column(String(8), nullable=False, default="rule")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasons_ct: Mapped[bytes | None] = mapped_column(LargeBinary)
    reasons_dek_wrapped: Mapped[bytes | None] = mapped_column(LargeBinary)


class RubricRule(Base, TimestampMixin):
    """User-editable classification rule (plan §8, §14 Phase 2).

    The rule engine in :mod:`app.services.classification.rubric` reads
    every active rule ordered by :attr:`priority` DESC (higher wins).
    ``match`` is a JSONB predicate, ``action`` is a JSONB verdict.

    Attributes:
        id: Primary key.
        user_id: Owner (rules are scoped per user).
        priority: Higher wins on conflicts. Defaults to 0.
        match: Predicate JSON. Supports ``from_domain``, ``from_email``,
            ``subject_regex``, ``has_label``, ``list_unsubscribe_present``,
            ``header_equals``, combined via an implicit AND.
        action: Verdict JSON. Must set ``label`` + ``confidence``;
            optional ``reasons`` list.
        version: Incremented each time the rule set mutates; plumbed
            into :attr:`Classification.rubric_version`.
        active: Soft-delete switch.
    """

    __tablename__ = "rubric_rules"
    __table_args__ = (Index("ix_rubric_rules_user_priority", "user_id", "priority"),)

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    match: Mapped[Any] = mapped_column(json_column(), nullable=False)
    action: Mapped[Any] = mapped_column(json_column(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PromptVersion(Base, TimestampMixin):
    """Registry row for a versioned prompt bundle (plan §6).

    Populated at process start by
    :class:`app.services.prompts.registry.PromptRegistry` from
    ``packages/prompts/<key>/v<n>.md``. Schema-wise this table is the
    source of truth the LLM-call logger FK-references — the file on disk
    still exists but the DB row is what auditing queries join against.

    Attributes:
        id: Primary key.
        name: Prompt key (``triage`` / ``summarize_relevant`` / ...).
        version: Integer version; forms ``UNIQUE(name, version)``.
        content: The raw prompt body (markdown).
        content_hash: SHA-256 digest of :attr:`content` — unique across
            the whole table so identical bodies under different names
            still round-trip.
        model: Default model identifier this prompt was validated against.
        params: JSON of default call params (``temperature``,
            ``max_tokens``, ``cache_tier`` ...).
        activated_at: When this version became the active one; ``None``
            for historical versions.
    """

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
        UniqueConstraint("content_hash", name="uq_prompt_versions_content_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    params: Mapped[Any] = mapped_column(json_column(), nullable=False, default=dict)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromptCallLog(Base, TimestampMixin):
    """One row per LLM call (plan §8, §6 cost controls).

    Powers the per-day cost report in CloudWatch and the per-email
    decision audit trail. ``status='fallback'`` means the primary
    provider was skipped in favour of the fallback chain.

    Attributes:
        id: Primary key.
        prompt_version_id: FK into :class:`PromptVersion`; required.
        email_id: Target email, if the call was email-scoped.
        model: Provider model identifier.
        tokens_in: Billed input tokens.
        tokens_out: Billed output tokens.
        tokens_cache_read: Cache-hit token count (provider-reported).
        tokens_cache_write: Cache-write token count.
        cost_usd: Provider-reported cost in USD.
        latency_ms: Wall-clock latency of the call.
        status: ``ok`` / ``fallback`` / ``error`` / ``skipped``.
        provider: ``gemini`` / ``anthropic_direct`` / ``bedrock`` / ...
        run_id: Optional digest-run that triggered the call.
    """

    __tablename__ = "prompt_call_log"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok','fallback','error','skipped')",
            name="ck_prompt_call_log_status",
        ),
        Index("ix_prompt_call_log_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"),
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_cache_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_cache_write: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6),
        nullable=False,
        default=Decimal("0"),
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ok")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    run_id: Mapped[uuid.UUID | None] = mapped_column()


_SUMMARY_KIND_CHOICES = ("email", "tech_news_cluster")
"""Allowed values for ``summaries.kind`` (plan §8)."""


class Summary(Base, TimestampMixin):
    """Per-email or per-cluster summary (plan §8, §14 Phase 3, §20.10).

    ``body_md_ct`` and ``entities_ct`` are envelope ciphertexts — the
    plaintext ``body_md`` + entity list never hit disk. Cluster rows
    carry ``email_id=NULL`` and a ``cluster_id`` FK into
    :class:`TechNewsCluster`.

    Attributes:
        id: Primary key.
        kind: ``email`` or ``tech_news_cluster``.
        email_id: Target email for ``kind='email'``; ``None`` for
            cluster summaries.
        cluster_id: Target cluster for ``kind='tech_news_cluster'``;
            ``None`` otherwise.
        prompt_version_id: FK into :class:`PromptVersion`.
        model: Provider-scoped model identifier.
        tokens_in: Input tokens billed.
        tokens_out: Output tokens billed.
        body_md_ct: Envelope ciphertext over the plaintext summary.
        entities_ct: Envelope ciphertext over the JSON entity chips.
        cache_hit: True when the provider reported cache-read tokens
            for this call (plan §14 Phase 3 cache-hit metrics).
        confidence: Calibrated ``[0, 1]``; ≥ 0.55 ships in the digest.
        batch_id: Optional Batch API job id when the summary was
            produced in an overnight batch; ``None`` for sync calls.
    """

    __tablename__ = "summaries"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('email','tech_news_cluster')",
            name="ck_summaries_kind",
        ),
        CheckConstraint(
            "(kind = 'email' AND email_id IS NOT NULL AND cluster_id IS NULL)"
            " OR (kind = 'tech_news_cluster' AND cluster_id IS NOT NULL AND email_id IS NULL)",
            name="ck_summaries_kind_target",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_summaries_confidence_range",
        ),
        UniqueConstraint("email_id", name="uq_summaries_email_id"),
        UniqueConstraint("cluster_id", name="uq_summaries_cluster_id"),
        Index("ix_summaries_kind_created_at", "kind", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"),
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tech_news_clusters.id", ondelete="CASCADE"),
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
    )
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body_md_ct: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    entities_ct: Mapped[bytes | None] = mapped_column(LargeBinary)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=Decimal("0.000"),
    )
    batch_id: Mapped[str | None] = mapped_column(String(128))


class TechNewsCluster(Base, TimestampMixin):
    """Newsletter cluster envelope (plan §14 Phase 3).

    One row per ``(user_id, cluster_key, run_id)`` scope — the digest
    composer joins ``summaries.cluster_id`` → ``TechNewsCluster`` →
    ``tech_news_cluster_members`` to render a topic list with source
    chips.

    Attributes:
        id: Primary key.
        user_id: Owner.
        run_id: Optional digest-run scope; ``None`` for ad-hoc clusters.
        cluster_key: Stable slug — matches
            :attr:`EmailSummary.cluster_key` / the routing label in
            :class:`KnownNewsletter`.
        topic_hint: Optional human-readable topic caption.
        member_count: Denormalized count for quick UI rendering.
    """

    __tablename__ = "tech_news_clusters"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "cluster_key",
            "run_id",
            name="uq_tech_news_clusters_user_key_run",
        ),
        Index("ix_tech_news_clusters_user_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column()
    cluster_key: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TechNewsClusterMember(Base, TimestampMixin):
    """Join table linking cluster rows to their source emails.

    Attributes:
        cluster_id: FK into :class:`TechNewsCluster`.
        email_id: FK into :class:`Email` — the source newsletter.
        sort_order: Order of inclusion in the cluster (0-indexed).
    """

    __tablename__ = "tech_news_cluster_members"
    __table_args__ = (
        UniqueConstraint(
            "cluster_id",
            "email_id",
            name="uq_tech_news_cluster_members_cluster_email",
        ),
        Index(
            "ix_tech_news_cluster_members_cluster_sort",
            "cluster_id",
            "sort_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tech_news_clusters.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class KnownNewsletter(Base, TimestampMixin):
    """Curated list-ID / domain → cluster mapping (plan §8, §14 Phase 3).

    The tech-news router reads this table to deterministically bucket
    incoming newsletters into stable cluster keys before falling back to
    a domain-based heuristic.

    Attributes:
        id: Primary key.
        match: JSON predicate (same shape as :attr:`RubricRule.match`);
            supports ``list_id_equals``, ``from_domain``, ``from_email``,
            ``subject_regex``, combined via implicit AND.
        cluster_key: Target cluster slug — feeds
            :attr:`Summary.cluster_id` via :class:`TechNewsCluster`.
        topic_hint: Human-readable topic caption the prompt uses verbatim.
        maintainer: Who owns this entry (``seed`` / ``user:<id>``).
    """

    __tablename__ = "known_newsletters"
    __table_args__ = (Index("ix_known_newsletters_cluster_key", "cluster_key"),)

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    match: Mapped[Any] = mapped_column(json_column(), nullable=False)
    cluster_key: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    maintainer: Mapped[str] = mapped_column(String(64), nullable=False, default="seed")


class KnownWasteSender(Base, TimestampMixin):
    """Curated list of senders the rule engine short-circuits to ``waste``.

    Plan §8 ``known_waste_senders`` — the rule engine consults this list
    before touching the user's own rubric, so new seed entries don't
    require a user-scoped copy.

    Attributes:
        id: Primary key.
        match: JSON predicate; supports the same keys as
            :attr:`RubricRule.match`.
        added_by: Who added the entry (``seed`` / ``user:<id>`` / ...).
        reason: Short human-readable justification.
    """

    __tablename__ = "known_waste_senders"

    id: Mapped[uuid.UUID] = mapped_column(default=_uuid_factory, primary_key=True)
    match: Mapped[Any] = mapped_column(json_column(), nullable=False)
    added_by: Mapped[str] = mapped_column(String(64), nullable=False, default="seed")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")


__all__ = [
    "Base",
    "Classification",
    "ConnectedAccount",
    "Email",
    "EmailContentBlob",
    "KnownNewsletter",
    "KnownWasteSender",
    "OAuthToken",
    "PromptCallLog",
    "PromptVersion",
    "RubricRule",
    "Summary",
    "SyncCursor",
    "TechNewsCluster",
    "TechNewsClusterMember",
    "TimestampMixin",
    "User",
]
