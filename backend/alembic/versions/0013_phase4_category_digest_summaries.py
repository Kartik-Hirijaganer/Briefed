"""Phase 4 category digest summaries.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add run-scoped category digest summaries."""
    op.add_column("summaries", sa.Column("run_id", postgresql.UUID(as_uuid=True)))
    op.add_column("summaries", sa.Column("category", sa.String(24)))
    op.create_foreign_key(
        "fk_summaries_run_id_digest_runs",
        "summaries",
        "digest_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("ck_summaries_kind_target", "summaries", type_="check")
    op.drop_constraint("ck_summaries_kind", "summaries", type_="check")
    op.create_check_constraint(
        "ck_summaries_kind",
        "summaries",
        "kind IN ('email','tech_news_cluster','category_digest')",
    )
    op.create_check_constraint(
        "ck_summaries_kind_target",
        "summaries",
        "(kind = 'email' AND email_id IS NOT NULL AND cluster_id IS NULL)"
        " OR (kind = 'tech_news_cluster' AND cluster_id IS NOT NULL AND email_id IS NULL)"
        " OR (kind = 'category_digest' AND email_id IS NULL AND cluster_id IS NULL"
        " AND run_id IS NOT NULL AND category IS NOT NULL)",
    )
    op.create_index(
        "uq_summaries_run_category",
        "summaries",
        ["run_id", "category"],
        unique=True,
        postgresql_where=sa.text("kind = 'category_digest'"),
    )


def downgrade() -> None:
    """Remove run-scoped category digest summaries."""
    op.drop_index("uq_summaries_run_category", table_name="summaries")
    op.execute(sa.text("DELETE FROM summaries WHERE kind = 'category_digest'"))
    op.drop_constraint("ck_summaries_kind_target", "summaries", type_="check")
    op.drop_constraint("ck_summaries_kind", "summaries", type_="check")
    op.create_check_constraint(
        "ck_summaries_kind",
        "summaries",
        "kind IN ('email','tech_news_cluster')",
    )
    op.create_check_constraint(
        "ck_summaries_kind_target",
        "summaries",
        "(kind = 'email' AND email_id IS NOT NULL AND cluster_id IS NULL)"
        " OR (kind = 'tech_news_cluster' AND cluster_id IS NOT NULL AND email_id IS NULL)",
    )
    op.drop_constraint("fk_summaries_run_id_digest_runs", "summaries", type_="foreignkey")
    op.drop_column("summaries", "category")
    op.drop_column("summaries", "run_id")
