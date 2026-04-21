"""``List-Unsubscribe`` header parser (plan §14 Phase 5).

Implements RFC 2369 (``List-Unsubscribe``) + RFC 8058 (one-click POST)
with deliberate leniency — real-world headers from marketing senders
are messy. Features:

* Angle-bracketed entries separated by commas, whitespace, or
  newlines. Nested commas inside URLs are tolerated because we split
  on the brackets, not the commas.
* Missing brackets (occasionally seen from older ESPs) fall back to a
  whitespace/comma split.
* Classification by URI scheme (``mailto:`` / ``http:`` / ``https:``)
  is case-insensitive; HTTP URLs are surfaced as-is.
* ``List-Unsubscribe-Post`` presence with ``List-Unsubscribe=One-Click``
  flags the :attr:`UnsubscribeAction.one_click` signal — the UI uses
  this to confirm a POST-vs-GET action with the user.

Kept standalone from :mod:`app.services.gmail.parser`'s ``_parse_list_unsubscribe``
so Phase 5's hygiene pipeline (the SQL aggregator) can consume raw
headers from any provider, including IMAP/Outlook when those land in
1.2+. Gmail ingestion continues to call its own copy — refactoring
that to share this module is Phase 8 cleanup.

This module is intentionally pure-functional + side-effect-free so
unit tests can sweep 20+ header variants cheaply
(:mod:`backend.tests.unit.test_unsubscribe_parser`).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

_BRACKET_RE = re.compile(r"<\s*([^<>]+?)\s*>")
"""Match ``<...>`` segments, tolerating internal whitespace + newlines."""

_SCHEME_RE = re.compile(r"^\s*([a-zA-Z][a-zA-Z0-9+\-.]*):", re.ASCII)
"""Match a URI scheme at the start of a string (RFC 3986 §3.1)."""

_MAX_ENTRIES = 16
"""Cap entries we persist so a pathological header cannot blow up rows."""

_MAX_URL_LEN = 2048
"""Cap a single URL at a conservative length."""


class UnsubscribeAction(BaseModel):
    """Normalized, actionable ``List-Unsubscribe`` payload.

    Attributes:
        http_urls: Every HTTP/HTTPS URL advertised by the sender, in
            the order they appeared. Consumers should prefer the
            first HTTPS entry; ``https://`` is not enforced because
            some ESPs still emit HTTP (a Phase 5 suggestion should
            surface it, the UI decides whether to show it).
        mailto: First ``mailto:`` URI (there is rarely more than one;
            we keep only the first for the UI).
        one_click: True when ``List-Unsubscribe-Post: List-Unsubscribe=One-Click``
            was present alongside ``List-Unsubscribe``. Per RFC 8058 the
            recipient may POST to any HTTP URL to unsubscribe without
            further confirmation; the UI uses this to render a
            "one-click" badge.
    """

    model_config = ConfigDict(frozen=True)

    http_urls: tuple[str, ...] = Field(
        default=(),
        description="HTTP/HTTPS action URLs in original order.",
    )
    mailto: str | None = Field(
        default=None,
        description="mailto: URI (first one wins).",
    )
    one_click: bool = Field(
        default=False,
        description="RFC 8058 one-click POST is supported.",
    )

    @property
    def has_any_action(self) -> bool:
        """Return ``True`` when at least one actionable target exists."""
        return bool(self.http_urls) or self.mailto is not None

    @property
    def preferred_url(self) -> str | None:
        """Return the best URL for the UI to link to, if any.

        Ordering:
        1. First HTTPS URL.
        2. First HTTP URL.
        3. The ``mailto:`` URI.
        4. ``None`` when the header held nothing actionable.

        Returns:
            The chosen URL, or ``None``.
        """
        for url in self.http_urls:
            if url.lower().startswith("https://"):
                return url
        if self.http_urls:
            return self.http_urls[0]
        return self.mailto


def parse_list_unsubscribe(
    header: str | None,
    post_header: str | None = None,
) -> UnsubscribeAction | None:
    """Parse ``List-Unsubscribe`` (+ optional ``-Post``) into an action.

    Args:
        header: Raw ``List-Unsubscribe`` value (may be ``None`` when the
            sender did not declare one).
        post_header: Raw ``List-Unsubscribe-Post`` value.

    Returns:
        The parsed :class:`UnsubscribeAction`, or ``None`` when nothing
        actionable could be extracted (no valid URL + no ``mailto:``).
    """
    if not header or not header.strip():
        return None

    entries = _extract_entries(header)
    http_urls: list[str] = []
    mailto: str | None = None

    for entry in entries:
        scheme = _scheme_of(entry)
        if scheme is None:
            continue
        if scheme == "mailto":
            if mailto is None and len(entry) <= _MAX_URL_LEN:
                mailto = entry
            continue
        if scheme in {"http", "https"} and len(entry) <= _MAX_URL_LEN and entry not in http_urls:
            http_urls.append(entry)

    if not http_urls and mailto is None:
        return None

    one_click = _is_one_click(post_header)
    return UnsubscribeAction(
        http_urls=tuple(http_urls[:_MAX_ENTRIES]),
        mailto=mailto,
        one_click=one_click,
    )


def _extract_entries(header: str) -> list[str]:
    """Split a raw header into candidate URI strings.

    First pass extracts angle-bracketed entries. If none exist (some
    legacy ESPs drop the brackets), fall back to a comma/whitespace
    split.

    Args:
        header: Raw header value.

    Returns:
        Candidate entries stripped of surrounding whitespace. Entries
        are de-duped by case-insensitive string equality.
    """
    bracketed = [re.sub(r"\s+", "", match) for match in _BRACKET_RE.findall(header)]
    if bracketed:
        return _dedupe(bracketed)
    # Fallback: comma- or whitespace-delimited.
    loose = [chunk.strip().strip(";,") for chunk in re.split(r"[,\s]+", header)]
    return _dedupe([chunk for chunk in loose if chunk])


def _dedupe(entries: list[str]) -> list[str]:
    """Return ``entries`` with duplicates removed, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for entry in entries:
        key = entry.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _scheme_of(entry: str) -> str | None:
    """Return the lowercased URI scheme of ``entry``, or ``None``.

    Args:
        entry: Candidate URI string.

    Returns:
        The scheme in lowercase (e.g. ``"mailto"``), or ``None`` when
        no scheme is present.
    """
    match = _SCHEME_RE.match(entry)
    if match is None:
        return None
    return match.group(1).lower()


def _is_one_click(post_header: str | None) -> bool:
    """Return ``True`` when the sender advertises RFC 8058 one-click.

    The contract (RFC 8058 §3.1) requires the exact pair:

    ::

        List-Unsubscribe-Post: List-Unsubscribe=One-Click

    Whitespace is tolerated; case-insensitive match on both the key
    and the value.

    Args:
        post_header: Raw ``List-Unsubscribe-Post`` value (may be
            ``None``).

    Returns:
        ``True`` when the expected directive is present.
    """
    if not post_header:
        return False
    normalized = re.sub(r"\s+", "", post_header).lower()
    return "list-unsubscribe=one-click" in normalized


__all__ = ["UnsubscribeAction", "parse_list_unsubscribe"]
