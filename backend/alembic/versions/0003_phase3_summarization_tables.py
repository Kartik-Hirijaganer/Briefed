"""Phase 3 summarization + tech-news clustering tables.

Creates ``summaries``, ``tech_news_clusters``, ``tech_news_cluster_members``,
``known_newsletters`` per plan §8, §14 Phase 3, and §20.10 (envelope-
encrypted ``summaries.body_md_ct`` + ``summaries.entities_ct``).

A small seed of ``known_newsletters`` rows pre-populates the tech-news
router so the first run produces useful clusters without hand-tagging.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-19 23:30:00
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb() -> sa.types.TypeEngine[object]:
    """Return JSONB on Postgres, JSON elsewhere (SQLite test path)."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


_KNOWN_NEWSLETTER_SEED: tuple[tuple[dict[str, object], str, str, str], ...] = (
    (
        {"list_id_equals": "llm-research.list-id.example"},
        "llm-research",
        "Open-weight and frontier LLM research.",
        "seed",
    ),
    (
        {"from_domain": "aws.amazon.com"},
        "cloud-providers",
        "AWS / hyperscaler product updates.",
        "seed",
    ),
    (
        {"from_domain": "googleblog.com"},
        "cloud-providers",
        "Google Cloud product and research updates.",
        "seed",
    ),
    (
        {"from_domain": "substack.com", "subject_regex": r"(?i)weekly (ai|ml)"},
        "ai-weekly-digests",
        "Weekly AI/ML digests.",
        "seed",
    ),
    (
        {"from_domain": "hackernewsletter.com"},
        "tech-news",
        "Generalist tech news roundup.",
        "seed",
    ),
)


def upgrade() -> None:
    """Apply the Phase 3 schema."""
    op.create_table(
        "known_newsletters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("match", _jsonb(), nullable=False),
        sa.Column("cluster_key", sa.String(64), nullable=False),
        sa.Column("topic_hint", sa.Text, nullable=False, server_default=""),
        sa.Column("maintainer", sa.String(64), nullable=False, server_default="seed"),
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
        "ix_known_newsletters_cluster_key",
        "known_newsletters",
        ["cluster_key"],
    )

    op.create_table(
        "tech_news_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("cluster_key", sa.String(64), nullable=False),
        sa.Column("topic_hint", sa.Text, nullable=False, server_default=""),
        sa.Column("member_count", sa.Integer, nullable=False, server_default="0"),
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
        sa.UniqueConstraint(
            "user_id",
            "cluster_key",
            "run_id",
            name="uq_tech_news_clusters_user_key_run",
        ),
    )
    op.create_index(
        "ix_tech_news_clusters_user_created_at",
        "tech_news_clusters",
        ["user_id", "created_at"],
    )

    op.create_table(
        "tech_news_cluster_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tech_news_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
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
        sa.UniqueConstraint(
            "cluster_id",
            "email_id",
            name="uq_tech_news_cluster_members_cluster_email",
        ),
    )
    op.create_index(
        "ix_tech_news_cluster_members_cluster_sort",
        "tech_news_cluster_members",
        ["cluster_id", "sort_order"],
    )

    op.create_table(
        "summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column(
            "email_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tech_news_clusters.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("body_md_ct", sa.LargeBinary, nullable=False),
        sa.Column("entities_ct", sa.LargeBinary),
        sa.Column(
            "cache_hit",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "confidence",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("batch_id", sa.String(128)),
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
            "kind IN ('email','tech_news_cluster')",
            name="ck_summaries_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'email' AND email_id IS NOT NULL AND cluster_id IS NULL)"
            " OR (kind = 'tech_news_cluster' AND cluster_id IS NOT NULL AND email_id IS NULL)",
            name="ck_summaries_kind_target",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_summaries_confidence_range",
        ),
        sa.UniqueConstraint("email_id", name="uq_summaries_email_id"),
        sa.UniqueConstraint("cluster_id", name="uq_summaries_cluster_id"),
    )
    op.create_index(
        "ix_summaries_kind_created_at",
        "summaries",
        ["kind", "created_at"],
    )

    bind = op.get_bind()
    seed_insert = sa.text(
        "INSERT INTO known_newsletters (id, match, cluster_key, topic_hint, maintainer,"
        " created_at, updated_at) VALUES (:id, :match, :cluster_key, :topic_hint, :maintainer,"
        " now(), now())"
    )
    for match, cluster_key, topic_hint, maintainer in _KNOWN_NEWSLETTER_SEED:
        bind.execute(
            seed_insert,
            {
                "id": _uuid(),
                "match": json.dumps(match),
                "cluster_key": cluster_key,
                "topic_hint": topic_hint,
                "maintainer": maintainer,
            },
        )


def downgrade() -> None:
    """Revert the Phase 3 schema."""
    op.drop_index("ix_summaries_kind_created_at", table_name="summaries")
    op.drop_table("summaries")
    op.drop_index(
        "ix_tech_news_cluster_members_cluster_sort",
        table_name="tech_news_cluster_members",
    )
    op.drop_table("tech_news_cluster_members")
    op.drop_index(
        "ix_tech_news_clusters_user_created_at",
        table_name="tech_news_clusters",
    )
    op.drop_table("tech_news_clusters")
    op.drop_index(
        "ix_known_newsletters_cluster_key",
        table_name="known_newsletters",
    )
    op.drop_table("known_newsletters")


def _uuid() -> str:
    """Return a fresh UUIDv4 string for portable Alembic seed inserts."""
    return str(uuid.uuid4())
