"""Add the per-category digest dispatch claim table.

Run finalization enqueues one category digest per (digest run, category)
once the run's per-email summaries drain. The claim used to be the
``category_digests_enqueued`` key in ``digest_runs.stats``, which
concurrent finalizers read from stale ORM copies and rewrote.
``digest_run_category_digest_claims`` holds it as a composite primary key,
taken with ``INSERT ... ON CONFLICT DO NOTHING``.

No backfill: a run still in flight during the deploy can enqueue a
category digest once more. The digest worker skips a category whose
digest row already exists, so only a duplicate racing the first one
costs an extra LLM call.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-27 21:35:44
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "digest_run_category_digest_claims"


def upgrade() -> None:
    """Create the category digest claim table."""
    op.create_table(
        _TABLE,
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["digest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "category"),
    )


def downgrade() -> None:
    """Drop the category digest claim table."""
    op.drop_table(_TABLE)
