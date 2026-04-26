"""Phase 5 unsubscribe + inbox-hygiene tables.

Creates ``unsubscribe_suggestions`` per plan §8, §14 Phase 5, and §20.10
(envelope-encrypted ``rationale_ct``). No seed data — rows are produced
by the worker aggregate from real email traffic.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-20 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> sa.types.TypeEngine[object]:
    """Return JSONB on Postgres, JSON elsewhere (SQLite test path)."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _citext(length: int) -> sa.types.TypeEngine[str]:
    """Return CITEXT on Postgres, a fallback VARCHAR elsewhere."""
    return sa.String(length).with_variant(postgresql.CITEXT(), "postgresql")


def upgrade() -> None:
    """Apply the Phase 5 schema."""
    op.create_table(
        "unsubscribe_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connected_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender_domain", _citext(253), nullable=False),
        sa.Column("sender_email", _citext(320), nullable=False),
        sa.Column(
            "frequency_30d",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "engagement_score",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "waste_rate",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("list_unsubscribe", _jsonb()),
        sa.Column(
            "confidence",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "decision_source",
            sa.String(8),
            nullable=False,
            server_default="rule",
        ),
        sa.Column("rationale_ct", sa.LargeBinary, nullable=False),
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "dismissed",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("last_email_at", sa.DateTime(timezone=True)),
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
            "sender_email",
            name="uq_unsubscribe_suggestions_account_sender",
        ),
        sa.CheckConstraint(
            "engagement_score >= 0 AND engagement_score <= 1",
            name="ck_unsubscribe_suggestions_engagement_range",
        ),
        sa.CheckConstraint(
            "waste_rate >= 0 AND waste_rate <= 1",
            name="ck_unsubscribe_suggestions_waste_range",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_unsubscribe_suggestions_confidence_range",
        ),
        sa.CheckConstraint(
            "decision_source IN ('rule','model')",
            name="ck_unsubscribe_suggestions_decision_source",
        ),
        sa.CheckConstraint(
            "frequency_30d >= 0",
            name="ck_unsubscribe_suggestions_frequency_non_negative",
        ),
    )
    op.create_index(
        "ix_unsubscribe_suggestions_account_score",
        "unsubscribe_suggestions",
        ["account_id", "engagement_score"],
    )
    op.create_index(
        "ix_unsubscribe_suggestions_account_dismissed",
        "unsubscribe_suggestions",
        ["account_id", "dismissed"],
    )


def downgrade() -> None:
    """Revert the Phase 5 schema."""
    op.drop_index(
        "ix_unsubscribe_suggestions_account_dismissed",
        table_name="unsubscribe_suggestions",
    )
    op.drop_index(
        "ix_unsubscribe_suggestions_account_score",
        table_name="unsubscribe_suggestions",
    )
    op.drop_table("unsubscribe_suggestions")
