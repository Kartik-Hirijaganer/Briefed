"""Phase 1 ingestion tables.

Creates ``users``, ``connected_accounts``, ``oauth_tokens``,
``sync_cursors``, ``emails`` and ``email_content_blobs`` per plan §8
+ §19.7. Partitioning is deferred (§20.2) — plain indexed tables are
sufficient at single-user volume.

Revision ID: 0001
Revises:
Create Date: 2026-04-19 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _citext() -> sa.types.TypeEngine[str]:
    """Return CITEXT on Postgres, TEXT elsewhere."""
    return sa.Text().with_variant(postgresql.CITEXT(), "postgresql")


def _text_array() -> sa.types.TypeEngine[list[str]]:
    """Return TEXT[] on Postgres, JSON on other dialects."""
    return sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql")


def _jsonb() -> sa.types.TypeEngine[object]:
    """Return JSONB on Postgres, JSON elsewhere."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Apply the Phase 1 schema."""
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", _citext(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column("tz", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('active','disabled','deleted')",
            name="ck_users_status",
        ),
    )

    op.create_table(
        "connected_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(16), nullable=False, server_default="gmail"),
        sa.Column("email", _citext(), nullable=False),
        sa.Column("gmail_account_id", sa.String(128)),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("daily_budget_in", sa.Integer, nullable=False, server_default="500000"),
        sa.Column("daily_budget_out", sa.Integer, nullable=False, server_default="100000"),
        sa.Column(
            "exclude_from_global_digest",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "auto_scan_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "email", name="uq_connected_accounts_user_email"),
        sa.CheckConstraint("provider = 'gmail'", name="ck_connected_accounts_provider"),
        sa.CheckConstraint(
            "status IN ('active','disabled','revoked')",
            name="ck_connected_accounts_status",
        ),
    )

    op.create_table(
        "oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connected_accounts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("access_token_ct", sa.LargeBinary, nullable=False),
        sa.Column("refresh_token_ct", sa.LargeBinary, nullable=False),
        sa.Column("scope", _text_array(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "sync_cursors",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connected_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("history_id", sa.BigInteger),
        sa.Column("last_full_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_incremental_at", sa.DateTime(timezone=True)),
        sa.Column("stale", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connected_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gmail_message_id", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("internal_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_addr", _citext(), nullable=False),
        sa.Column("to_addrs", _text_array(), nullable=False),
        sa.Column("cc_addrs", _text_array(), nullable=False),
        sa.Column("subject", sa.Text, nullable=False, server_default=""),
        sa.Column("snippet", sa.Text, nullable=False, server_default=""),
        sa.Column("labels", _text_array(), nullable=False),
        sa.Column("list_unsubscribe", _jsonb()),
        sa.Column("content_hash", sa.LargeBinary, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("raw_s3_key", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "account_id",
            "gmail_message_id",
            name="uq_emails_account_message",
        ),
    )
    op.create_index(
        "ix_emails_account_internal_date",
        "emails",
        ["account_id", "internal_date"],
    )

    op.create_table(
        "email_content_blobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("storage_backend", sa.String(8), nullable=False, server_default="pg"),
        sa.Column("object_key", sa.Text),
        sa.Column("plain_text_excerpt", sa.Text, nullable=False, server_default=""),
        sa.Column("html_sanitized_key", sa.Text),
        sa.Column(
            "quoted_text_removed",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("language", sa.String(16)),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "storage_backend IN ('pg','s3')",
            name="ck_email_content_blobs_storage",
        ),
    )


def downgrade() -> None:
    """Revert the Phase 1 schema."""
    op.drop_table("email_content_blobs")
    op.drop_index("ix_emails_account_internal_date", table_name="emails")
    op.drop_table("emails")
    op.drop_table("sync_cursors")
    op.drop_table("oauth_tokens")
    op.drop_table("connected_accounts")
    op.drop_table("users")
