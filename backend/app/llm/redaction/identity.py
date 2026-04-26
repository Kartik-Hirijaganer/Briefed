"""User-identity scrubber (Track B Phase 2).

Replaces user-specific strings (own email, full name, account aliases,
opaque user-id) with stable placeholders **before** the regex sanitizer
runs. The deterministic identity scrub is what actually moves the
needle on "OR cannot tie a request to *this* user" — Presidio's NER is
too fuzzy to rely on for the user's own tokens.
"""

from __future__ import annotations

import re

from app.llm.redaction.types import RedactionResult


class IdentityScrubber:
    """Replace user-specific tokens with stable placeholders.

    Construction takes a mapping of placeholder to candidate strings.
    Replacements are case-insensitive and run longest-match-first so
    ``"Kartik Hirijaganer"`` is replaced as a single token before the
    scrubber considers ``"Kartik H"``.

    Attributes:
        name: Stable slug used in logs / counts.
    """

    name: str = "identity"

    def __init__(self, identities: dict[str, list[str]]) -> None:
        """Compile a single regex per placeholder.

        Args:
            identities: ``{"<USER_EMAIL>": ["a@b.com", "alias@b.com"],
                "<USER_NAME>": ["Kartik Hirijaganer", "Kartik H"], ...}``.

        Raises:
            ValueError: If a placeholder maps to an empty / whitespace
                candidate that would match anything.
        """
        compiled: list[tuple[str, re.Pattern[str]]] = []
        for placeholder, candidates in identities.items():
            for candidate in candidates:
                if not candidate or not candidate.strip():
                    raise ValueError(
                        f"empty candidate for {placeholder!r}",
                    )
            ordered = sorted(candidates, key=len, reverse=True)
            joined = "|".join(re.escape(c) for c in ordered)
            compiled.append(
                (placeholder, re.compile(joined, re.IGNORECASE)),
            )
        self._compiled = compiled

    def sanitize(self, text: str) -> RedactionResult:
        """Replace every identity match with the placeholder for its kind.

        Args:
            text: Raw input.

        Returns:
            :class:`RedactionResult` with one count per matched placeholder.
        """
        if not text or not self._compiled:
            return RedactionResult(text=text)

        reversal_map: dict[str, str] = {}
        counts: dict[str, int] = {}
        rewritten = text

        for placeholder, pattern in self._compiled:
            kind = placeholder.strip("<>")
            counter = 0

            def _swap(
                match: re.Match[str],
                _placeholder: str = placeholder,
                _kind: str = kind,
            ) -> str:
                nonlocal counter
                token = f"<{_kind}_{counter}>"
                reversal_map[token] = match.group(0)
                counter += 1
                return token

            rewritten, swapped = pattern.subn(_swap, rewritten)
            if swapped:
                counts[kind] = counts.get(kind, 0) + swapped

        return RedactionResult(
            text=rewritten,
            reversal_map=reversal_map,
            counts_by_kind=counts,
        )


__all__ = ["IdentityScrubber"]
