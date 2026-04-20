"""Injectable UTC clock (plan §7).

Every module that needs ``now()`` routes through :func:`utcnow` so tests
can freeze time without monkeypatching :mod:`datetime`.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC :class:`datetime`.

    Prefer this helper over ``datetime.now(UTC)`` so tests can swap it via
    :class:`Clock` fixtures.

    Returns:
        Timezone-aware UTC timestamp.
    """
    return datetime.now(UTC)
