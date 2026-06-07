"""Add the execute-unsubscribe lifecycle to ``unsubscribe_suggestions``.

ADR 0014 lets a user-initiated action actually execute an unsubscribe (behind
the ``unsubscribe_execute`` flag, default off). This records the real lifecycle
per row: a ``pending`` → ``unsubscribed`` / ``manual_required`` / ``failed``
status, how it was performed, attempt/success timestamps, an error note, and
the ``manual_url`` the user must open when a one-click POST is not possible.

``execute_status`` is ``NOT NULL`` with a ``'pending'`` server default so the
single pre-existing row (and any others) backfills cleanly.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-06 00:00:01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "unsubscribe_suggestions"
_STATUS_CONSTRAINT = "ck_unsubscribe_suggestions_execute_status"
_STATUS_CHECK = "execute_status IN ('pending','unsubscribed','manual_required','failed')"


def upgrade() -> None:
    """Add the execute lifecycle columns + status check constraint."""
    op.add_column(
        _TABLE,
        sa.Column("execute_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column(_TABLE, sa.Column("executed_via", sa.String(16)))
    op.add_column(_TABLE, sa.Column("execute_attempted_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("executed_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("execute_error", sa.Text))
    op.add_column(_TABLE, sa.Column("manual_url", sa.Text))

    # SQLite cannot ALTER TABLE ADD CONSTRAINT; tests build the schema from the
    # ORM metadata (which carries the constraint) so only Postgres needs it here.
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(_STATUS_CONSTRAINT, _TABLE, _STATUS_CHECK)


def downgrade() -> None:
    """Drop the execute lifecycle columns + status check constraint."""
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(_STATUS_CONSTRAINT, _TABLE, type_="check")
    op.drop_column(_TABLE, "manual_url")
    op.drop_column(_TABLE, "execute_error")
    op.drop_column(_TABLE, "executed_at")
    op.drop_column(_TABLE, "execute_attempted_at")
    op.drop_column(_TABLE, "executed_via")
    op.drop_column(_TABLE, "execute_status")
