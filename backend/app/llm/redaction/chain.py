"""Sanitizer chain (Track B Phase 4).

Composes a tuple of :class:`Sanitizer` implementations into a single
``Sanitizer``. Each pass runs on the rewritten text from the previous
pass; ``reversal_map`` and ``counts_by_kind`` are merged across passes
(later wins on collision, counts accumulate).

Order matters at the call site, not here. The Briefed defaults run
identity → regex → presidio so user-specific tokens get a stable
placeholder before anything else runs.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.llm.redaction.types import RedactionResult, Sanitizer


class SanitizerChain:
    """Run a tuple of sanitizers in sequence.

    Attributes:
        name: Stable slug used in logs / counts.
        sanitizers: The composed pass list.
    """

    name: str = "chain"

    def __init__(self, sanitizers: Iterable[Sanitizer]) -> None:
        """Capture the pass list.

        Args:
            sanitizers: Ordered iterable of sanitizers to run.
        """
        self.sanitizers: tuple[Sanitizer, ...] = tuple(sanitizers)

    def sanitize(self, text: str) -> RedactionResult:
        """Run every sanitizer in order; merge results.

        Args:
            text: Raw input.

        Returns:
            :class:`RedactionResult` whose ``text`` is the output of the
            final pass, ``reversal_map`` is the merged map (later wins),
            and ``counts_by_kind`` is the summed histogram.
        """
        rewritten = text
        merged_reversal: dict[str, str] = {}
        merged_counts: dict[str, int] = {}

        for sanitizer in self.sanitizers:
            step = sanitizer.sanitize(rewritten)
            rewritten = step.text
            merged_reversal.update(step.reversal_map)
            for kind, count in step.counts_by_kind.items():
                merged_counts[kind] = merged_counts.get(kind, 0) + count

        return RedactionResult(
            text=rewritten,
            reversal_map=merged_reversal,
            counts_by_kind=merged_counts,
        )


__all__ = ["SanitizerChain"]
