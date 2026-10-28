"""Add the per-account unsubscribe-hygiene dispatch claim table.

Classify workers enqueue one unsubscribe-hygiene job per (digest run,
connected account). The claim used to be a key in ``digest_runs.stats``,
which concurrent workers read stale and rewrote, so prod enqueued the
job twice on 6 of 14 days. ``digest_run_hygiene_claims`` holds the claim
as a composite primary key, taken with ``INSERT ... ON CONFLICT DO
NOTHING``.

No backfill: completed runs never claim again. A run still in flight
during the deploy can enqueue hygiene once more for an account whose
legacy ``stats`` marker is already set, which is the bug's own worst case.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-27 21:26:47
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "digest_run_hygiene_claims"
_ACCOUNT_INDEX = "ix_digest_run_hygiene_claims_account"


def upgrade() -> None:
    """Create the hygiene claim table and its account index."""
    op.create_table(
        _TABLE,
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["connected_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["digest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "account_id"),
    )
    op.create_index(_ACCOUNT_INDEX, _TABLE, ["account_id"], unique=False)


def downgrade() -> None:
    """Drop the hygiene claim table."""
    op.drop_index(_ACCOUNT_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
