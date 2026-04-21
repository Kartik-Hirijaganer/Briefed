"""Phase 6 frontend preferences and digest-run ledger.

Creates the small tables the PWA needs for settings persistence,
manual-run polling, and history rendering.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-21 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> sa.types.TypeEngine[object]:
    """Return JSONB on Postgres, JSON elsewhere."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Apply the Phase 6 schema."""
    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "auto_execution_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "digest_send_hour_utc",
            sa.Integer,
            nullable=False,
            server_default="13",
        ),
        sa.Column(
            "redact_pii",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "secure_offline_mode",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "retention_policy_json",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'{}'"),
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
        sa.CheckConstraint(
            "digest_send_hour_utc >= 0 AND digest_send_hour_utc <= 23",
            name="ck_user_preferences_digest_hour",
        ),
    )

    op.create_table(
        "digest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("trigger_type", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("stats", _jsonb(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("cost_cents", sa.Integer),
        sa.Column("error", sa.Text),
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
            "status IN ('queued','running','complete','failed')",
            name="ck_digest_runs_status",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('scheduled','manual')",
            name="ck_digest_runs_trigger_type",
        ),
    )
    op.create_index(
        "ix_digest_runs_user_started_at",
        "digest_runs",
        ["user_id", "started_at"],
    )


def downgrade() -> None:
    """Remove the Phase 6 schema."""
    op.drop_index("ix_digest_runs_user_started_at", table_name="digest_runs")
    op.drop_table("digest_runs")
    op.drop_table("user_preferences")
