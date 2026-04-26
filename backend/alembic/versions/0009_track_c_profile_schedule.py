"""Track C — Profile + schedule columns on the users table.

Adds the 11 user-tunable values that drive the Track C profile API and
the slot-matching scheduler:

* Profile fields consumed by Track B's ``IdentityScrubber`` (display
  name, email + redaction aliases) and the UI (theme preference,
  Presidio toggle).
* Schedule fields consumed by ``app.core.scheduling.is_due`` —
  cadence, local time slots, IANA timezone.
* Idempotency lock columns (``current_run_id`` /
  ``current_run_started_at``) and the ``last_run_finished_at`` cursor
  used by the fanout filter.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-25 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _string_array() -> sa.types.TypeEngine[object]:
    """Return ``TEXT[]`` on Postgres, JSON on SQLite (matches StringArray)."""
    return sa.JSON().with_variant(postgresql.ARRAY(sa.Text()), "postgresql")


_SCHEDULE_FREQUENCY_VALUES = ("once_daily", "twice_daily", "disabled")
_THEME_PREFERENCE_VALUES = ("system", "light", "dark")


def upgrade() -> None:
    """Apply the Track C profile + schedule columns."""
    op.add_column(
        "users",
        sa.Column("email_aliases", _string_array(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "users",
        sa.Column(
            "redaction_aliases",
            _string_array(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "schedule_frequency",
            sa.String(16),
            nullable=False,
            server_default="once_daily",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "schedule_times_local",
            _string_array(),
            nullable=False,
            server_default="{08:00}",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "schedule_timezone",
            sa.String(64),
            nullable=False,
            server_default="UTC",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "presidio_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "theme_preference",
            sa.String(16),
            nullable=False,
            server_default="system",
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_run_finished_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "users",
        sa.Column("current_run_id", sa.Text),
    )
    op.add_column(
        "users",
        sa.Column("current_run_started_at", sa.DateTime(timezone=True)),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_users_schedule_frequency",
            "users",
            f"schedule_frequency IN {_SCHEDULE_FREQUENCY_VALUES}",
        )
        op.create_check_constraint(
            "ck_users_theme_preference",
            "users",
            f"theme_preference IN {_THEME_PREFERENCE_VALUES}",
        )
        op.create_check_constraint(
            "ck_users_schedule_frequency_times_consistency",
            "users",
            "(schedule_frequency = 'once_daily'"
            " AND array_length(schedule_times_local, 1) = 1)"
            " OR (schedule_frequency = 'twice_daily'"
            " AND array_length(schedule_times_local, 1) = 2)"
            " OR (schedule_frequency = 'disabled')",
        )
    else:
        # SQLite — array_length() is unavailable. Skip the array-length
        # consistency constraint; enum constraints still run.
        op.create_check_constraint(
            "ck_users_schedule_frequency",
            "users",
            f"schedule_frequency IN {_SCHEDULE_FREQUENCY_VALUES}",
        )
        op.create_check_constraint(
            "ck_users_theme_preference",
            "users",
            f"theme_preference IN {_THEME_PREFERENCE_VALUES}",
        )


def downgrade() -> None:
    """Remove the Track C profile + schedule columns."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "ck_users_schedule_frequency_times_consistency",
            "users",
            type_="check",
        )
    op.drop_constraint("ck_users_theme_preference", "users", type_="check")
    op.drop_constraint("ck_users_schedule_frequency", "users", type_="check")
    op.drop_column("users", "current_run_started_at")
    op.drop_column("users", "current_run_id")
    op.drop_column("users", "last_run_finished_at")
    op.drop_column("users", "theme_preference")
    op.drop_column("users", "presidio_enabled")
    op.drop_column("users", "schedule_timezone")
    op.drop_column("users", "schedule_times_local")
    op.drop_column("users", "schedule_frequency")
    op.drop_column("users", "redaction_aliases")
    op.drop_column("users", "email_aliases")
