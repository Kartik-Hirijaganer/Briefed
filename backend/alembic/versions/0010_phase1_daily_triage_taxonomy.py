"""Phase 1 daily-triage taxonomy.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_LABEL_CHECK = (
    "label IN ("
    "'must_read','good_to_read','ignore','waste',"
    "'newsletter','job_candidate','needs_review'"
    ")"
)
_NEW_LABEL_CHECK = "label IN ('must_read','good_to_read','ignore')"


def upgrade() -> None:
    """Apply Phase 1 taxonomy and rule-name changes."""
    op.add_column(
        "classifications",
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "rubric_rules",
        sa.Column(
            "name",
            sa.String(length=120),
            nullable=False,
            server_default="Untitled rule",
        ),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE classifications SET needs_review = :flag WHERE label = 'needs_review'"),
        {"flag": True},
    )
    bind.execute(
        sa.text(
            "UPDATE classifications SET label = 'ignore' WHERE label IN ('waste', 'needs_review')",
        ),
    )
    bind.execute(
        sa.text(
            "UPDATE classifications SET label = 'good_to_read' "
            "WHERE label IN ('newsletter', 'job_candidate')",
        ),
    )
    bind.execute(sa.text("UPDATE classifications SET is_job_candidate = :flag"), {"flag": False})

    with op.batch_alter_table("classifications") as batch_op:
        batch_op.drop_constraint("ck_classifications_label", type_="check")
        batch_op.create_check_constraint("ck_classifications_label", _NEW_LABEL_CHECK)


def downgrade() -> None:
    """Revert Phase 1 taxonomy and rule-name changes."""
    with op.batch_alter_table("classifications") as batch_op:
        batch_op.drop_constraint("ck_classifications_label", type_="check")
        batch_op.create_check_constraint("ck_classifications_label", _OLD_LABEL_CHECK)

    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE classifications SET label = 'needs_review' WHERE needs_review = :flag"),
        {"flag": True},
    )

    op.drop_column("rubric_rules", "name")
    op.drop_column("classifications", "needs_review")
