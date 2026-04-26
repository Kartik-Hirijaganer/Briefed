"""Track B redaction_summary column on prompt_call_log.

Adds the ``redaction_summary`` JSONB column per Track B Phase 5 / ADR
0010. The column stores ``{kind: count}`` from the sanitizer chain and
is ``NULL`` when no sanitizer ran. The sanitizer's ``reversal_map`` is
never stored here.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> sa.types.TypeEngine[object]:
    """Return JSONB on Postgres, JSON elsewhere."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Add the ``redaction_summary`` column."""
    op.add_column(
        "prompt_call_log",
        sa.Column(
            "redaction_summary",
            _jsonb(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Drop the ``redaction_summary`` column."""
    op.drop_column("prompt_call_log", "redaction_summary")
