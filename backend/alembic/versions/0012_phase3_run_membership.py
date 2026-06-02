"""Phase 3 run membership.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the explicit digest-run email membership table."""
    op.create_table(
        "digest_run_emails",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("digest_runs.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_digest_run_emails_email",
        "digest_run_emails",
        ["email_id"],
    )


def downgrade() -> None:
    """Drop the explicit digest-run email membership table."""
    op.drop_index("ix_digest_run_emails_email", table_name="digest_run_emails")
    op.drop_table("digest_run_emails")
