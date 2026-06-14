"""Add legal-consent fields to ``users``.

Real Gmail data processing is now gated behind explicit acceptance of the
current privacy policy and terms of service. Version ``0`` means the user has
never accepted that policy family.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-14 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"


def upgrade() -> None:
    """Add legal-consent version and audit columns."""
    op.add_column(
        _TABLE,
        sa.Column(
            "privacy_policy_version_accepted",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "terms_version_accepted",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(_TABLE, sa.Column("legal_accepted_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("legal_accepted_user_agent", sa.Text()))


def downgrade() -> None:
    """Drop legal-consent version and audit columns."""
    op.drop_column(_TABLE, "legal_accepted_user_agent")
    op.drop_column(_TABLE, "legal_accepted_at")
    op.drop_column(_TABLE, "terms_version_accepted")
    op.drop_column(_TABLE, "privacy_policy_version_accepted")
