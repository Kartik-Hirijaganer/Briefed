"""Drop the users.theme_preference column.

The Notion UI revamp collapses Briefed to a single fixed theme (no
light / dark / system switch), so the server no longer mirrors a per-user
theme override. This removes the ``theme_preference`` column and its
``ck_users_theme_preference`` CHECK constraint, both added in revision 0009.
The downgrade re-adds the column with its original ``'system'`` default and
constraint so the migration is reversible.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-01 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_THEME_PREFERENCE_VALUES = ("system", "light", "dark")


def upgrade() -> None:
    """Drop the ``theme_preference`` column + its CHECK constraint."""
    op.drop_constraint("ck_users_theme_preference", "users", type_="check")
    op.drop_column("users", "theme_preference")


def downgrade() -> None:
    """Re-add ``theme_preference`` with its original default + CHECK constraint."""
    op.add_column(
        "users",
        sa.Column(
            "theme_preference",
            sa.String(16),
            nullable=False,
            server_default="system",
        ),
    )
    op.create_check_constraint(
        "ck_users_theme_preference",
        "users",
        f"theme_preference IN {_THEME_PREFERENCE_VALUES}",
    )
