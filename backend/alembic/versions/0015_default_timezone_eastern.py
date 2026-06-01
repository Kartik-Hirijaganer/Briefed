"""Default account timezones to America/New_York instead of UTC.

The owner is in the US Eastern zone, so new accounts should default to
``America/New_York`` (which tracks EST/EDT) rather than UTC. This flips the
``server_default`` on both ``users.tz`` and ``users.schedule_timezone`` and
backfills rows still holding the old ``'UTC'`` default so the existing
account's scheduled scans fire at the right wall-clock time. Rows that were
explicitly set to some other zone are left untouched.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-01 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_DEFAULT = "UTC"
_NEW_DEFAULT = "America/New_York"
_TZ_COLUMNS = ("tz", "schedule_timezone")


def upgrade() -> None:
    """Set the Eastern default and backfill rows still on the UTC default."""
    for column in _TZ_COLUMNS:
        op.alter_column(
            "users",
            column,
            existing_type=sa.String(64),
            existing_nullable=False,
            server_default=_NEW_DEFAULT,
        )
        op.execute(
            sa.text(f"UPDATE users SET {column} = :new WHERE {column} = :old").bindparams(
                new=_NEW_DEFAULT,
                old=_OLD_DEFAULT,
            )
        )


def downgrade() -> None:
    """Restore the UTC default and revert the backfilled rows."""
    for column in _TZ_COLUMNS:
        op.alter_column(
            "users",
            column,
            existing_type=sa.String(64),
            existing_nullable=False,
            server_default=_OLD_DEFAULT,
        )
        op.execute(
            sa.text(f"UPDATE users SET {column} = :old WHERE {column} = :new").bindparams(
                new=_NEW_DEFAULT,
                old=_OLD_DEFAULT,
            )
        )
