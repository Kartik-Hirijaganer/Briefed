"""Phase 2 remove jobs and Presidio defaults.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> sa.types.TypeEngine[object]:
    """Return JSONB on Postgres, JSON elsewhere."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Drop jobs schema and disable the legacy Presidio toggle."""
    op.drop_index("ix_job_filters_user_active", table_name="job_filters")
    op.drop_table("job_filters")
    op.drop_index("ix_job_matches_passed_filter", table_name="job_matches")
    op.drop_table("job_matches")

    with op.batch_alter_table("classifications") as batch_op:
        batch_op.drop_column("is_job_candidate")

    op.execute(sa.text("UPDATE users SET presidio_enabled = false"))
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("presidio_enabled", server_default=sa.false())


def downgrade() -> None:
    """Recreate jobs schema and restore the old Presidio default."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("presidio_enabled", server_default=sa.true())

    with op.batch_alter_table("classifications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_job_candidate",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    op.create_table(
        "job_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("company", sa.Text, nullable=False),
        sa.Column("location", sa.Text),
        sa.Column("remote", sa.Boolean),
        sa.Column("comp_min", sa.Integer),
        sa.Column("comp_max", sa.Integer),
        sa.Column("currency", sa.String(3)),
        sa.Column("comp_phrase", sa.Text),
        sa.Column("seniority", sa.String(16)),
        sa.Column("source_url", sa.Text),
        sa.Column(
            "match_score",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("filter_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "passed_filter",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("match_reason_ct", sa.LargeBinary, nullable=False),
        sa.Column("match_reason_dek_wrapped", sa.LargeBinary),
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
            "match_score >= 0 AND match_score <= 1",
            name="ck_job_matches_match_score_range",
        ),
        sa.CheckConstraint(
            "(comp_min IS NULL AND comp_max IS NULL)"
            " OR (comp_min IS NOT NULL AND currency IS NOT NULL)"
            " OR (comp_max IS NOT NULL AND currency IS NOT NULL)",
            name="ck_job_matches_currency_required",
        ),
        sa.CheckConstraint(
            "comp_min IS NULL OR comp_max IS NULL OR comp_min <= comp_max",
            name="ck_job_matches_comp_range_order",
        ),
    )
    op.create_index(
        "ix_job_matches_passed_filter",
        "job_matches",
        ["passed_filter", "created_at"],
    )

    op.create_table(
        "job_filters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("predicate", _jsonb(), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "active",
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
        sa.UniqueConstraint("user_id", "name", name="uq_job_filters_user_name"),
    )
    op.create_index(
        "ix_job_filters_user_active",
        "job_filters",
        ["user_id", "active"],
    )
