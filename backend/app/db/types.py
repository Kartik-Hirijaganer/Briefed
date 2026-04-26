"""Portable SQLAlchemy column types (plan §8).

Production runs on Supabase / RDS Postgres and uses PG-native types
(CITEXT, JSONB, ARRAY, BYTEA). Tests run on SQLite, which lacks those
types. :class:`JsonType`, :class:`CiText`, and :class:`StringArray`
pick the right backend via ``with_variant`` so one ORM model serves
both worlds.
"""

from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.types import TypeDecorator, TypeEngine


def json_column() -> TypeEngine[object]:
    """Return a JSON column that becomes JSONB on Postgres.

    SQLAlchemy's :class:`sqlalchemy.JSON` is portable; the PG variant
    unlocks the operator / index support we rely on for JSONB queries.

    Returns:
        A column type suitable for ORM ``mapped_column`` declarations.
    """
    return JSON().with_variant(JSONB(), "postgresql")


def citext_column(length: int | None = None) -> TypeEngine[str]:
    """Return a case-insensitive text column.

    Maps to ``CITEXT`` on Postgres and plain ``String`` / ``Text`` on
    SQLite — the latter relies on app-level casing for equality.

    Args:
        length: Optional column length; ``None`` selects ``Text``.

    Returns:
        A string-valued column type.
    """
    base: TypeEngine[str] = String(length) if length else Text()
    return base.with_variant(CITEXT(), "postgresql")


class StringArray(TypeDecorator[list[str]]):
    """Portable ``TEXT[]`` column backed by JSON on SQLite.

    Attributes:
        impl: Underlying column type (:class:`sqlalchemy.JSON`).
        cache_ok: Safe to cache per the SQLAlchemy contract.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: object) -> TypeEngine[object]:
        """Select the native array type on Postgres.

        Args:
            dialect: The active SQLAlchemy dialect.

        Returns:
            The dialect-specific column type descriptor.
        """
        name = getattr(dialect, "name", "")
        if name == "postgresql":
            return ARRAY(Text())  # type: ignore[return-value]
        return JSON()

    def process_bind_param(
        self,
        value: list[str] | None,
        dialect: object,
    ) -> list[str] | None:
        """Coerce the inbound value to a list before persistence."""
        if value is None:
            return None
        return list(value)

    def process_result_value(
        self,
        value: list[str] | None,
        dialect: object,
    ) -> list[str] | None:
        """Return the list as-is from the driver."""
        return None if value is None else list(value)
