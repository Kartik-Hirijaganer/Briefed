"""Newsletter cluster router (plan §14 Phase 3).

Given one :class:`app.db.models.Email`, deterministically assign a
``cluster_key`` the tech-news summarizer uses to group related
newsletters. The router runs in two passes:

1. **Curated map** — :class:`app.db.models.KnownNewsletter` rows match
   on ``list_id_equals`` / ``from_domain`` / ``from_email`` /
   ``subject_regex`` (same predicate shape as ``rubric_rules`` — an
   implicit AND across keys, higher-priority matches win via insertion
   order). This is the path the plan §14 Phase 3 test case covers
   ("cluster router deterministic for known List-IDs").

2. **Fallback heuristic** — derive the cluster key from the sender's
   domain (strip public TLD suffix, lowercase, replace dots with
   hyphens, cap at 48 chars). Guarantees a stable key even for
   newsletters we have no curated entry for.

The router is pure: given the same input + the same curated rules, it
always returns the same :class:`ClusterRoute`. That matters for the
"deterministic for known List-IDs" exit criterion and for the eval
suite (we replay fixtures across branches without re-tagging).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import KnownNewsletter

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger(__name__)


_SLUG_UNSAFE_RE = re.compile(r"[^a-z0-9]+")
"""Characters replaced by ``-`` when slugifying a fallback cluster key."""

_PUBLIC_TLD_SUFFIXES: tuple[str, ...] = (
    ".co.uk",
    ".com.au",
    ".com",
    ".net",
    ".org",
    ".io",
    ".ai",
    ".sh",
    ".dev",
    ".so",
)
"""Common public suffixes stripped from the sender domain before slugifying."""


@dataclass(frozen=True)
class ClusterRoute:
    """Resolved routing for one email.

    Attributes:
        cluster_key: Stable slug (≤ 64 chars); used as
            :attr:`app.db.models.TechNewsCluster.cluster_key`.
        topic_hint: Human-readable caption the prompt sees.
        matched_known_id: Primary key of the matching
            :class:`KnownNewsletter` row when the curated map fired;
            ``None`` when the fallback heuristic produced the key.
    """

    cluster_key: str
    topic_hint: str
    matched_known_id: UUID | None


class ClusterRouter:
    """Deterministic newsletter → cluster router.

    Attributes:
        rules: Ordered curated entries; first match wins.
    """

    def __init__(self, *, rules: tuple[KnownNewsletter, ...]) -> None:
        """Snapshot the curated rules into an in-memory list.

        Args:
            rules: Iterable of :class:`KnownNewsletter` rows. Callers
                pass them in the order they want precedence applied —
                ``load_default_router`` orders by ``maintainer`` so seed
                rows lose to user overrides.
        """
        self._rules = tuple(rules)

    def route(
        self,
        *,
        from_addr: str,
        subject: str,
        list_id: str | None,
    ) -> ClusterRoute:
        """Return the :class:`ClusterRoute` for one email.

        Args:
            from_addr: Raw ``From`` address (plaintext, lowercased
                internally).
            subject: Decoded subject line.
            list_id: Parsed ``List-ID`` header, when present. Gmail
                supplies this verbatim; we match against it first.

        Returns:
            :class:`ClusterRoute` with a stable ``cluster_key``.
        """
        from_lower = from_addr.strip().lower()
        list_lower = _normalize_list_id(list_id)

        for rule in self._rules:
            match = rule.match if isinstance(rule.match, dict) else {}
            if _rule_matches(
                match,
                from_addr=from_lower,
                subject=subject,
                list_id=list_lower,
            ):
                return ClusterRoute(
                    cluster_key=str(rule.cluster_key),
                    topic_hint=str(rule.topic_hint or ""),
                    matched_known_id=rule.id,
                )

        fallback_key = _fallback_cluster_key(from_lower)
        return ClusterRoute(
            cluster_key=fallback_key,
            topic_hint="",
            matched_known_id=None,
        )


def _rule_matches(
    match: Mapping[str, object],
    *,
    from_addr: str,
    subject: str,
    list_id: str | None,
) -> bool:
    """Evaluate a curated rule against one email.

    Args:
        match: JSON predicate from :attr:`KnownNewsletter.match`.
        from_addr: Lowercased ``From`` address.
        subject: Subject line.
        list_id: Lowercased ``List-ID`` header, or ``None``.

    Returns:
        ``True`` when every key in ``match`` is satisfied.
    """
    if not match:
        return False
    if "list_id_equals" in match:
        expected = str(match["list_id_equals"]).strip().lower()
        if not list_id or list_id != expected:
            return False
    if "from_domain" in match:
        expected = str(match["from_domain"]).strip().lower()
        if not from_addr.endswith("@" + expected) and not from_addr.endswith(
            "." + expected,
        ):
            return False
    if "from_email" in match and from_addr != str(match["from_email"]).strip().lower():
        return False
    if "subject_regex" in match:
        pattern = str(match["subject_regex"])
        if re.search(pattern, subject) is None:
            return False
    return True


def _normalize_list_id(raw: str | None) -> str | None:
    """Strip angle brackets + optional descriptive prefix from a ``List-ID``.

    Gmail typically returns ``"Mailing List <list-id.example>"``. We keep
    the bracketed id and lowercase it so curated rules can match on the
    canonical string.

    Args:
        raw: Header value.

    Returns:
        Lowercased id, or ``None`` when ``raw`` is blank.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if "<" in value and ">" in value:
        start = value.rfind("<") + 1
        end = value.find(">", start)
        if end != -1:
            value = value[start:end]
    return value.lower()


def _fallback_cluster_key(from_addr: str) -> str:
    """Derive a stable cluster key from the sender address.

    Args:
        from_addr: Lowercased sender address.

    Returns:
        Slugified domain (≤ 48 chars), or ``"unsorted"`` when the
        address has no host portion.
    """
    host = from_addr.rsplit("@", maxsplit=1)[-1] if "@" in from_addr else from_addr
    if not host:
        return "unsorted"
    base = host.strip(".")
    for suffix in _PUBLIC_TLD_SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base.startswith("www."):
        base = base[4:]
    slug = _SLUG_UNSAFE_RE.sub("-", base).strip("-")
    if not slug:
        return "unsorted"
    return slug[:48]


async def load_default_router(session: AsyncSession) -> ClusterRouter:
    """Build the default :class:`ClusterRouter` from the DB.

    Orders user-maintained rows ahead of seed rows so custom entries
    win ties. Called once per run from the worker handler.

    Args:
        session: Active async session.

    Returns:
        A :class:`ClusterRouter` seeded with every
        :class:`KnownNewsletter` row.
    """
    stmt = select(KnownNewsletter).order_by(
        (KnownNewsletter.maintainer == "seed").asc(),
        KnownNewsletter.created_at.asc(),
    )
    rows: Iterable[KnownNewsletter] = (await session.execute(stmt)).scalars().all()
    return ClusterRouter(rules=tuple(rows))


__all__ = ["ClusterRoute", "ClusterRouter", "load_default_router"]
