"""Scope users and their encrypted data by runtime environment.

Dev and prod may temporarily share a PostgreSQL database, but their KMS keys
remain isolated. Namespacing the user identity prevents either runtime from
loading rows whose envelope ciphertext belongs to the other environment.

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-15 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"
_ENVIRONMENT_CHECK = "environment IN ('local','test','dev','prod')"
_ENVIRONMENT_CONSTRAINT = "ck_users_environment"
_ENVIRONMENT_EMAIL_CONSTRAINT = "uq_users_environment_email"
_LEGACY_EMAIL_CONSTRAINT = "users_email_key"


def upgrade() -> None:
    """Backfill existing shared rows to dev and add environment-scoped identity."""
    op.add_column(
        _TABLE,
        sa.Column(
            "environment",
            sa.String(16),
            nullable=False,
            server_default="dev",
        ),
    )
    op.drop_constraint(_LEGACY_EMAIL_CONSTRAINT, _TABLE, type_="unique")
    op.create_check_constraint(_ENVIRONMENT_CONSTRAINT, _TABLE, _ENVIRONMENT_CHECK)
    op.create_unique_constraint(
        _ENVIRONMENT_EMAIL_CONSTRAINT,
        _TABLE,
        ["environment", "email"],
    )
    op.alter_column(_TABLE, "environment", server_default=None)


def downgrade() -> None:
    """Restore global email uniqueness and remove environment ownership."""
    op.drop_constraint(_ENVIRONMENT_EMAIL_CONSTRAINT, _TABLE, type_="unique")
    op.drop_constraint(_ENVIRONMENT_CONSTRAINT, _TABLE, type_="check")
    op.create_unique_constraint(_LEGACY_EMAIL_CONSTRAINT, _TABLE, ["email"])
    op.drop_column(_TABLE, "environment")
