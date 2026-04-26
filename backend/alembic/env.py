"""Alembic migration environment for Briefed.

Phase 0: scaffolding only — no ORM models are registered yet, so
``autogenerate`` is a no-op. Phase 1 imports the SQLAlchemy metadata
from :mod:`app.db.models` and wires it into :data:`target_metadata`.

The database URL always comes from :func:`app.core.config.get_settings`
so local + Lambda + CI all read from the same source of truth.
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import engine_from_config, pool

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.engine import Connection


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """Pull the live DB URL from settings, stripping the asyncpg driver.

    Alembic's offline + online runners use the synchronous SQLAlchemy
    dialect (``postgresql+psycopg2``); the app uses asyncpg. We normalize
    here so migrations run under either runtime without config drift.

    Returns:
        A SQLAlchemy sync-dialect URL string suitable for Alembic.

    Raises:
        RuntimeError: If ``database_url`` is not configured.
    """
    from app.core.config import get_settings  # noqa: PLC0415 — lazy import

    settings = get_settings()
    url = settings.database_url
    if not url:
        raise RuntimeError(
            "database_url is not configured. Set BRIEFED_DATABASE_URL in .env "
            "or the corresponding SSM parameter before running migrations.",
        )
    return url.replace("+asyncpg", "")


# Phase 1: register the SQLAlchemy metadata so ``alembic revision
# --autogenerate`` picks up schema drift.
from app.db.models import Base  # noqa: E402 — needs the env-scoped path setup above

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection.

    Emits SQL to stdout instead of executing it — useful for CI review +
    human sign-off on destructive changes.
    """
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live Postgres connection."""
    section_name = config.config_ini_section
    ini_section = config.get_section(section_name) or {}
    ini_section["sqlalchemy.url"] = _resolve_database_url()

    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _configure_and_run(connection)


def _configure_and_run(connection: Connection) -> None:
    """Wire the Alembic context and execute the pending migrations.

    Split from :func:`run_migrations_online` so the transactional scope
    is visible at a glance.

    Args:
        connection: Live SQLAlchemy connection supplied by the engine
            context manager.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
