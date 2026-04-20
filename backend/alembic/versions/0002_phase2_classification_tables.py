"""Phase 2 classification, rubric, prompt-registry and cost-metering tables.

Creates ``classifications``, ``rubric_rules``, ``prompt_versions``,
``prompt_call_log``, ``known_waste_senders`` per plan §8, §14 Phase 2,
§19.7 (``decision_source`` column), and §20.10 (envelope-encrypted
``reasons_ct`` / ``reasons_dek_wrapped``).

A small seed of ``known_waste_senders`` rows is inserted so the rule
engine short-circuits the most common noise senders out of the box.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-19 23:00:00
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> sa.types.TypeEngine[object]:
    """Return JSONB on Postgres, JSON elsewhere (SQLite test path)."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


_KNOWN_WASTE_SEED: tuple[tuple[dict[str, object], str, str], ...] = (
    (
        {"from_domain": "mailer-daemon@googlemail.com"},
        "Google bounce notifications rarely need reading.",
        "seed",
    ),
    (
        {"from_domain": "noreply@reply.linkedin.com"},
        "LinkedIn bulk-notification loop; promote via rubric if desired.",
        "seed",
    ),
    (
        {"subject_regex": r"^(?i)\s*(viagra|crypto airdrop|lottery)"},
        "Obvious spam keywords.",
        "seed",
    ),
    (
        {"header_equals": {"Precedence": "bulk"}, "has_label": "SPAM"},
        "Provider-flagged spam with bulk precedence.",
        "seed",
    ),
)


def upgrade() -> None:
    """Apply the Phase 2 schema."""
    op.create_table(
        "prompt_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.LargeBinary, nullable=False),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("params", _jsonb(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),
        sa.UniqueConstraint("content_hash", name="uq_prompt_versions_content_hash"),
    )

    op.create_table(
        "classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("label", sa.String(24), nullable=False),
        sa.Column("score", sa.Numeric(4, 3), nullable=False),
        sa.Column("rubric_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "decision_source",
            sa.String(8),
            nullable=False,
            server_default="rule",
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reasons_ct", sa.LargeBinary),
        sa.Column("reasons_dek_wrapped", sa.LargeBinary),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "label IN ("
            "'must_read','good_to_read','ignore','waste',"
            "'newsletter','job_candidate','needs_review'"
            ")",
            name="ck_classifications_label",
        ),
        sa.CheckConstraint(
            "decision_source IN ('rule','model','hybrid')",
            name="ck_classifications_decision_source",
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1",
            name="ck_classifications_score_range",
        ),
    )

    op.create_table(
        "rubric_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("match", _jsonb(), nullable=False),
        sa.Column("action", _jsonb(), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_rubric_rules_user_priority",
        "rubric_rules",
        ["user_id", "priority"],
    )

    op.create_table(
        "prompt_call_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="SET NULL"),
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_cache_read", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_cache_write", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(12), nullable=False, server_default="ok"),
        sa.Column("provider", sa.String(32), nullable=False, server_default=""),
        sa.Column("run_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('ok','fallback','error','skipped')",
            name="ck_prompt_call_log_status",
        ),
    )
    op.create_index(
        "ix_prompt_call_log_created_at",
        "prompt_call_log",
        ["created_at"],
    )

    op.create_table(
        "known_waste_senders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("match", _jsonb(), nullable=False),
        sa.Column("added_by", sa.String(64), nullable=False, server_default="seed"),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    bind = op.get_bind()
    seed_insert = sa.text(
        "INSERT INTO known_waste_senders (id, match, added_by, reason, created_at, updated_at)"
        " VALUES (:id, :match, :added_by, :reason, now(), now())"
    )
    for match, reason, added_by in _KNOWN_WASTE_SEED:
        bind.execute(
            seed_insert,
            {
                "id": sa.func.gen_random_uuid() if bind.dialect.name == "postgresql" else _uuid(),
                "match": json.dumps(match),
                "added_by": added_by,
                "reason": reason,
            },
        )


def downgrade() -> None:
    """Revert the Phase 2 schema."""
    op.drop_table("known_waste_senders")
    op.drop_index("ix_prompt_call_log_created_at", table_name="prompt_call_log")
    op.drop_table("prompt_call_log")
    op.drop_index("ix_rubric_rules_user_priority", table_name="rubric_rules")
    op.drop_table("rubric_rules")
    op.drop_table("classifications")
    op.drop_table("prompt_versions")


def _uuid() -> str:
    """Return a fresh UUIDv4 string (SQLite seed path only)."""
    return str(uuid.uuid4())
