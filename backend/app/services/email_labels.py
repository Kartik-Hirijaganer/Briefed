"""Shared helpers for provider label semantics."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import any_, exists, func, literal, select
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Email

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


UNREAD_LABEL = "UNREAD"
"""Provider label that marks mail as unread in Gmail."""


def has_unread_label(labels: Sequence[str]) -> bool:
    """Return whether the provider labels contain ``UNREAD``.

    Args:
        labels: Provider label strings persisted on ``emails.labels``.

    Returns:
        True when the labels include Gmail's unread marker.
    """
    return UNREAD_LABEL in set(labels)


def drop_unread_label(labels: Sequence[str]) -> list[str]:
    """Return labels with Gmail's ``UNREAD`` marker removed.

    Args:
        labels: Provider label strings persisted on ``emails.labels``.

    Returns:
        A new list preserving the original order except for ``UNREAD``.
    """
    return [label for label in labels if label != UNREAD_LABEL]


def unread_email_filter(session: AsyncSession) -> ColumnElement[bool]:
    """Build a portable SQL predicate requiring ``emails.labels`` to contain ``UNREAD``.

    Args:
        session: Active SQLAlchemy session; used to choose the current
            dialect because Postgres stores labels as ``TEXT[]`` while
            SQLite tests store them as JSON arrays.

    Returns:
        SQLAlchemy boolean expression suitable for ``WHERE`` clauses.
    """
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        return literal(UNREAD_LABEL) == any_(Email.labels)

    label_values = func.json_each(Email.labels).table_valued("value").alias("email_label")
    return exists(
        select(literal(1)).select_from(label_values).where(label_values.c.value == UNREAD_LABEL),
    ).correlate(Email)


__all__ = ["UNREAD_LABEL", "drop_unread_label", "has_unread_label", "unread_email_filter"]
