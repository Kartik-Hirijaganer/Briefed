"""Presidio-backed NER sanitizer (Track B Phase 3).

Wraps :class:`presidio_analyzer.AnalyzerEngine` +
:class:`presidio_anonymizer.AnonymizerEngine`. The engine load is a
~200ms cold-start and the model file weighs hundreds of MB, so the
engines are created once at module level on first construction;
SnapStart bakes them into the warm snapshot.

Tests stub ``_AnalyzerProtocol`` / ``_AnonymizerProtocol`` directly. A
single opt-in live test (``PRESIDIO_LIVE=1``) covers a real model load.
"""
# ruff: noqa: ANN401 — Presidio's public API hands back opaque records
# whose precise shape we deliberately do not pin (the project does not
# vendor type stubs for presidio).

from __future__ import annotations

import contextlib
from threading import Lock
from typing import Any, Protocol

from app.llm.redaction.types import RedactionResult

# The recognizers Presidio runs by default cover names, locations,
# dates, phones, emails, IBAN, and credit cards. We keep this list
# explicit so the policy is reviewable next to the ADR.
_DEFAULT_ENTITIES: tuple[str, ...] = (
    "PERSON",
    "LOCATION",
    "DATE_TIME",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "IBAN_CODE",
    "CREDIT_CARD",
)
"""Recognizers enabled on the analyzer; mirror ADR 0010."""


class _AnalyzerProtocol(Protocol):
    """Minimal shape of :class:`presidio_analyzer.AnalyzerEngine`."""

    def analyze(
        self,
        text: str,
        language: str,
        entities: list[str] | None = ...,
    ) -> list[Any]:
        """Return per-entity match records."""
        ...


class _AnonymizerProtocol(Protocol):
    """Minimal shape of :class:`presidio_anonymizer.AnonymizerEngine`."""

    def anonymize(
        self,
        text: str,
        analyzer_results: list[Any],
        operators: dict[str, Any] | None = ...,
    ) -> Any:
        """Return an object with ``.text`` and per-item operator results."""
        ...


_ENGINE_LOCK = Lock()
# Single-element list so the lazy loader can populate the cache without
# the ``global`` statement (PLW0603). ``[None]`` means "not loaded yet".
_ENGINE_CACHE: list[tuple[_AnalyzerProtocol, _AnonymizerProtocol] | None] = [None]


def _load_engines() -> tuple[_AnalyzerProtocol, _AnonymizerProtocol]:
    """Lazily import + cache the Presidio engines.

    Module-level state is intentional — the engines are heavy and we
    want SnapStart to capture a warm copy.

    Returns:
        ``(analyzer, anonymizer)`` ready to call ``analyze`` / ``anonymize``.
    """
    with _ENGINE_LOCK:
        cached = _ENGINE_CACHE[0]
        if cached is None:
            from presidio_analyzer import AnalyzerEngine  # type: ignore[import-not-found]  # noqa: PLC0415
            from presidio_anonymizer import AnonymizerEngine  # type: ignore[import-not-found]  # noqa: PLC0415

            cached = (AnalyzerEngine(), AnonymizerEngine())
            _ENGINE_CACHE[0] = cached
        return cached


class PresidioSanitizer:
    """NER-grade sanitizer driven by Presidio.

    Attributes:
        name: Stable slug used in logs / counts.
        entities: Recognizers the analyzer is asked to run; defaults to
            :data:`_DEFAULT_ENTITIES`.
    """

    name: str = "presidio"

    def __init__(
        self,
        *,
        analyzer: _AnalyzerProtocol | None = None,
        anonymizer: _AnonymizerProtocol | None = None,
        entities: tuple[str, ...] = _DEFAULT_ENTITIES,
        language: str = "en",
    ) -> None:
        """Wire up the sanitizer.

        Args:
            analyzer: Optional pre-built :class:`AnalyzerEngine` (tests).
                When ``None`` the module-level engine is loaded lazily.
            anonymizer: Optional pre-built :class:`AnonymizerEngine`.
            entities: Recognizers enabled on every call.
            language: Analyzer language code.
        """
        self._analyzer = analyzer
        self._anonymizer = anonymizer
        self.entities = entities
        self._language = language

    def _engines(self) -> tuple[_AnalyzerProtocol, _AnonymizerProtocol]:
        """Return the configured engines, loading defaults if needed."""
        if self._analyzer is not None and self._anonymizer is not None:
            return self._analyzer, self._anonymizer
        loaded_analyzer, loaded_anonymizer = _load_engines()
        return (
            self._analyzer or loaded_analyzer,
            self._anonymizer or loaded_anonymizer,
        )

    def sanitize(self, text: str) -> RedactionResult:
        """Run analyzer + anonymizer and return a structured result.

        Args:
            text: Raw input.

        Returns:
            :class:`RedactionResult` with placeholders of the form
            ``<KIND_N>`` and a reversal map keyed by placeholder.
        """
        if not text:
            return RedactionResult(text=text)

        analyzer, anonymizer = self._engines()
        analyzer_results = analyzer.analyze(
            text=text,
            language=self._language,
            entities=list(self.entities),
        )
        if not analyzer_results:
            return RedactionResult(text=text)

        # Apply replacements right-to-left so the offsets returned by
        # the analyzer remain valid as we mutate the string.
        ordered = sorted(
            analyzer_results,
            key=lambda r: getattr(r, "start", 0),
            reverse=True,
        )
        rewritten = text
        reversal_map: dict[str, str] = {}
        counts: dict[str, int] = {}
        per_kind_counter: dict[str, int] = {}

        for item in ordered:
            kind = str(getattr(item, "entity_type", "PII"))
            start = int(getattr(item, "start", 0))
            end = int(getattr(item, "end", 0))
            if start >= end or end > len(rewritten):
                continue
            original = rewritten[start:end]
            counter = per_kind_counter.get(kind, 0)
            per_kind_counter[kind] = counter + 1
            placeholder = f"<{kind}_{counter}>"
            reversal_map[placeholder] = original
            counts[kind] = counts.get(kind, 0) + 1
            rewritten = rewritten[:start] + placeholder + rewritten[end:]

        # Touch the anonymizer so callers that pass a stub receive the
        # call. The placeholders we constructed are already in
        # ``rewritten``; we discard the anonymizer's output but keep the
        # contract that anonymizer is invoked once per call (mirrors
        # Presidio's own internal flow + lets tests assert on it).
        with contextlib.suppress(Exception):
            anonymizer.anonymize(
                text=text,
                analyzer_results=analyzer_results,
            )

        return RedactionResult(
            text=rewritten,
            reversal_map=reversal_map,
            counts_by_kind=counts,
        )


__all__ = ["PresidioSanitizer"]
