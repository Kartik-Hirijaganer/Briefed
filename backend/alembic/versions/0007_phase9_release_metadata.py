"""Phase 9 release_metadata ledger.

Creates the ``release_metadata`` table per plan §8 + §19.7. One row is
written by the ``deploy-prod`` workflow on every alias swing; a rollback
emits a fresh row with the previous version pointer (never mutates an
existing row).

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the Phase 9 schema."""
    op.create_table(
        "release_metadata",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("git_sha", sa.String(40), nullable=False),
        sa.Column("alembic_head", sa.String(32), nullable=False),
        sa.Column("api_schema_version", sa.String(32), nullable=False),
        sa.Column("db_schema_version", sa.String(32), nullable=False),
        sa.Column("frontend_build_id", sa.String(64)),
        sa.Column("prompt_bundle_version", sa.String(64)),
        sa.Column(
            "deployed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("notes", sa.Text),
        sa.UniqueConstraint(
            "version",
            "git_sha",
            name="uq_release_metadata_version_sha",
        ),
    )
    op.create_index(
        "ix_release_metadata_deployed_at",
        "release_metadata",
        ["deployed_at"],
    )


def downgrade() -> None:
    """Remove the Phase 9 schema."""
    op.drop_index(
        "ix_release_metadata_deployed_at",
        table_name="release_metadata",
    )
    op.drop_table("release_metadata")
