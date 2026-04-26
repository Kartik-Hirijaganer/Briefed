"""Sanitizer protocol + result value object (Track B Phase 1).

Every redaction implementation in :mod:`app.llm.redaction` exposes the
same shape so :class:`SanitizerChain` can compose them in any order.
The result is deliberately split into three fields so the caller can
log counts (safe), short-circuit reidentification on the response
(off by default — see ADR 0010), and feed downstream sanitizers a
sanitized text without losing context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RedactionResult:
    """Outcome of a single sanitizer pass.

    Attributes:
        text: Redacted text. ``placeholder`` tokens replace the matched
            spans.
        reversal_map: ``placeholder -> original`` mapping. **Never**
            persisted or logged outside the in-process call boundary
            (ADR 0010 code-review checklist).
        counts_by_kind: Histogram of redactions, keyed by kind tag (e.g.
            ``EMAIL``, ``PHONE``, ``USER_NAME``). Safe to log; this is
            what lands in ``prompt_call_log.redaction_summary``.
    """

    text: str
    reversal_map: dict[str, str] = field(default_factory=dict)
    counts_by_kind: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class Sanitizer(Protocol):
    """Structural protocol every sanitizer implements.

    A sanitizer is a pure function from ``str -> RedactionResult``. No
    network I/O, no DB access. Construction is allowed to load heavy
    artefacts (Presidio NER models) so module-level instantiation can
    amortise the cost.
    """

    def sanitize(self, text: str) -> RedactionResult:
        """Return a :class:`RedactionResult` for ``text``.

        Args:
            text: Raw input.

        Returns:
            :class:`RedactionResult` with the redacted text, the reversal
            map, and the per-kind counts.
        """
        ...


__all__ = ["RedactionResult", "Sanitizer"]
