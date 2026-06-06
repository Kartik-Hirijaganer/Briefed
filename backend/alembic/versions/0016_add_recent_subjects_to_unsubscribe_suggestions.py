"""Add ``recent_subjects`` to ``unsubscribe_suggestions``.

The hygiene aggregate already computes a short, newest-first list of
recent subject lines per sender (``SenderStats.recent_subjects``) and
discards it. This column persists that list so the unsubscribe cards can
show recent activity without rescanning emails. Subjects are plaintext in
``emails.subject`` (and already exposed via the email-list API), so the
column is stored in the clear — unlike the envelope-encrypted
``rationale_ct``.

The column is ``NOT NULL`` with an empty-array ``server_default`` so the
single pre-existing row (and any others) backfills cleanly to ``[]``
without a separate data migration.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-06 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "unsubscribe_suggestions"
_COLUMN = "recent_subjects"


def _string_array() -> sa.types.TypeEngine[object]:
    """Return ``TEXT[]`` on Postgres, JSON on SQLite (matches StringArray)."""
    return sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql")


def upgrade() -> None:
    """Add the ``recent_subjects`` array column with an empty default."""
    bind = op.get_bind()
    # PG array literal is ``{}``; the SQLite JSON fallback wants ``[]``.
    server_default = "{}" if bind.dialect.name == "postgresql" else "[]"
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            _string_array(),
            nullable=False,
            server_default=server_default,
        ),
    )


def downgrade() -> None:
    """Drop the ``recent_subjects`` column."""
    op.drop_column(_TABLE, _COLUMN)
