"""Zero-deps regex sanitizer (Track B Phase 1).

Covers the common deterministic shapes Presidio handles slowly or
unevenly: email addresses, phone numbers (E.164 + US-formatted), US
SSN, US ZIP, IPv4/v6, and URLs. Every match becomes ``<KIND_N>`` where
``N`` increments per kind across the call.

The regex set is intentionally short. Anything fuzzy (names, locations,
dates) belongs to :class:`PresidioSanitizer`; user-specific identifiers
belong to :class:`IdentityScrubber`.
"""

from __future__ import annotations

import re
from typing import Final

from app.llm.redaction.types import RedactionResult

# The order matters: longer / more specific patterns run first so e.g.
# ``URL`` matches the whole link before ``EMAIL`` claims the local-part
# of an embedded ``mailto:``. ``IP_V6`` runs before ``IP_V4`` so a v6
# address that happens to embed a v4 segment is taken whole.
_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "URL",
        re.compile(
            r"\b(?:https?|ftp)://[^\s<>\"']+",
            re.IGNORECASE,
        ),
    ),
    (
        "EMAIL",
        re.compile(
            r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
        ),
    ),
    (
        "IP_V6",
        re.compile(
            # Either a fully-expanded 8-group address, or a compressed
            # form using ``::``. Restricted to anywhere-in-string
            # (no \b at the colon boundary, since ``:`` is non-word).
            r"(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"
            r"|(?:[0-9a-fA-F]{1,4}:){1,7}:"
            r"|(?:[0-9a-fA-F]{1,4}:){1,6}(?::[0-9a-fA-F]{1,4})"
            r"|(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}"
            r"|(?:[0-9a-fA-F]{1,4}:){1,4}(?::[0-9a-fA-F]{1,4}){1,3}"
            r"|(?:[0-9a-fA-F]{1,4}:){1,3}(?::[0-9a-fA-F]{1,4}){1,4}"
            r"|(?:[0-9a-fA-F]{1,4}:){1,2}(?::[0-9a-fA-F]{1,4}){1,5}"
            r"|[0-9a-fA-F]{1,4}:(?:(?::[0-9a-fA-F]{1,4}){1,6})"
            r"|:(?:(?::[0-9a-fA-F]{1,4}){1,7}|:))",
        ),
    ),
    (
        "IP_V4",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b",
        ),
    ),
    (
        "SSN",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    ),
    (
        "PHONE",
        re.compile(
            r"(?:\+?\d{1,3}[\s.-]?)?"
            r"(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b",
        ),
    ),
    (
        "ZIP",
        re.compile(r"\b\d{5}(?:-\d{4})?\b"),
    ),
)
"""Pattern table consulted in order; first match wins for a span."""


class RegexSanitizer:
    """Apply the deterministic regex set to ``text``.

    Idempotent — re-running over an already-redacted string is a no-op
    because placeholders (``<EMAIL_0>`` etc.) do not match any pattern.

    Attributes:
        name: Stable slug used in logs / counts.
    """

    name: str = "regex"

    def sanitize(self, text: str) -> RedactionResult:
        """Walk every pattern and replace matches with ``<KIND_N>``.

        Args:
            text: Raw input.

        Returns:
            :class:`RedactionResult` with the redacted text, the reversal
            map, and the per-kind counts.
        """
        if not text:
            return RedactionResult(text=text)

        reversal_map: dict[str, str] = {}
        counts: dict[str, int] = {}
        rewritten = text

        for kind, pattern in _PATTERNS:
            counter = 0

            def _swap(match: re.Match[str], _kind: str = kind) -> str:
                nonlocal counter
                placeholder = f"<{_kind}_{counter}>"
                reversal_map[placeholder] = match.group(0)
                counter += 1
                return placeholder

            rewritten, swapped = pattern.subn(_swap, rewritten)
            if swapped:
                counts[kind] = counts.get(kind, 0) + swapped

        return RedactionResult(
            text=rewritten,
            reversal_map=reversal_map,
            counts_by_kind=counts,
        )


__all__ = ["RegexSanitizer"]
