"""Add the once-per-run tech-news cluster dispatch claim to ``digest_runs``.

Run finalization enqueues the newsletter cluster job once classification
drains. ``tech_news_cluster_enqueued_at`` records that dispatch with an
atomic ``UPDATE ... WHERE tech_news_cluster_enqueued_at IS NULL`` so
concurrent workers enqueue it at most once per run. It is nullable with no
backfill: in-flight and historical runs simply have no claim yet.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-27 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "digest_runs"
_COLUMN = "tech_news_cluster_enqueued_at"


def upgrade() -> None:
    """Add the nullable cluster dispatch claim column."""
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Drop the cluster dispatch claim column."""
    op.drop_column(_TABLE, _COLUMN)
