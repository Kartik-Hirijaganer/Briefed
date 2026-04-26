"""Unit tests for the Track B redaction layer (ADR 0010)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.llm.redaction import (
    IdentityScrubber,
    RegexSanitizer,
    SanitizerChain,
    build_default_chain,
)
from app.llm.redaction.presidio import PresidioSanitizer
from app.llm.redaction.types import RedactionResult, Sanitizer

# ----------------------------------------------------------------------
# RegexSanitizer (Phase 1)
# ----------------------------------------------------------------------


def test_regex_sanitizer_redacts_email() -> None:
    result = RegexSanitizer().sanitize("ping me at user@example.com please")
    assert "user@example.com" not in result.text
    assert "<EMAIL_0>" in result.text
    assert result.counts_by_kind["EMAIL"] == 1
    assert result.reversal_map["<EMAIL_0>"] == "user@example.com"


def test_regex_sanitizer_redacts_phone_us_format() -> None:
    result = RegexSanitizer().sanitize("call me on (415) 555-0100 today")
    assert "555-0100" not in result.text
    assert result.counts_by_kind["PHONE"] == 1


def test_regex_sanitizer_redacts_e164_phone() -> None:
    result = RegexSanitizer().sanitize("intl: +14155550100")
    assert result.counts_by_kind.get("PHONE") == 1


def test_regex_sanitizer_redacts_ssn() -> None:
    result = RegexSanitizer().sanitize("SSN 123-45-6789 is sensitive")
    assert "123-45-6789" not in result.text
    assert result.counts_by_kind["SSN"] == 1


def test_regex_sanitizer_redacts_zip() -> None:
    result = RegexSanitizer().sanitize("mail to 94110")
    assert result.counts_by_kind.get("ZIP") == 1


def test_regex_sanitizer_redacts_ipv4_and_ipv6() -> None:
    result = RegexSanitizer().sanitize(
        "from 10.0.0.1 routed via 2001:db8::1 today",
    )
    assert result.counts_by_kind.get("IP_V4") == 1
    assert result.counts_by_kind.get("IP_V6") == 1


def test_regex_sanitizer_redacts_url() -> None:
    result = RegexSanitizer().sanitize("see https://example.com/foo")
    assert result.counts_by_kind.get("URL") == 1
    assert "https://example.com/foo" not in result.text


def test_regex_sanitizer_idempotent() -> None:
    sanitizer = RegexSanitizer()
    once = sanitizer.sanitize("ping me at user@example.com")
    twice = sanitizer.sanitize(once.text)
    assert once.text == twice.text


def test_regex_sanitizer_empty_input() -> None:
    result = RegexSanitizer().sanitize("")
    assert result.text == ""
    assert result.counts_by_kind == {}
    assert result.reversal_map == {}


# ----------------------------------------------------------------------
# IdentityScrubber (Phase 2)
# ----------------------------------------------------------------------


def test_identity_longest_match_first() -> None:
    scrubber = IdentityScrubber(
        {"<USER_NAME>": ["Kartik H", "Kartik Hirijaganer"]},
    )
    result = scrubber.sanitize("Kartik Hirijaganer signed in.")
    assert "Kartik Hirijaganer" not in result.text
    assert "<USER_NAME_0>" in result.text
    assert result.counts_by_kind["USER_NAME"] == 1


def test_identity_case_folding() -> None:
    scrubber = IdentityScrubber({"<USER_EMAIL>": ["a@b.com"]})
    result = scrubber.sanitize("contact A@B.COM today")
    assert "A@B.COM" not in result.text
    assert result.counts_by_kind["USER_EMAIL"] == 1


def test_identity_then_regex_no_double_count() -> None:
    chain = SanitizerChain(
        [
            IdentityScrubber({"<USER_EMAIL>": ["me@example.com"]}),
            RegexSanitizer(),
        ],
    )
    result = chain.sanitize("me@example.com pinged other@example.com")
    assert result.counts_by_kind.get("USER_EMAIL") == 1
    assert result.counts_by_kind.get("EMAIL") == 1


def test_identity_empty_candidate_rejected() -> None:
    with pytest.raises(ValueError):
        IdentityScrubber({"<USER_NAME>": ["valid", "  "]})


def test_identity_missing_text_returns_empty() -> None:
    scrubber = IdentityScrubber({"<USER_NAME>": ["X"]})
    assert scrubber.sanitize("") == RedactionResult(text="")


# ----------------------------------------------------------------------
# PresidioSanitizer (Phase 3) — stubbed analyzer + anonymizer
# ----------------------------------------------------------------------


class _FakeMatch:
    def __init__(self, *, entity_type: str, start: int, end: int) -> None:
        self.entity_type = entity_type
        self.start = start
        self.end = end


class _FakeAnalyzer:
    def __init__(self, results: list[_FakeMatch]) -> None:
        self._results = results
        self.calls = 0

    def analyze(
        self,
        text: str,
        language: str,
        entities: list[str] | None = None,
    ) -> list[Any]:
        self.calls += 1
        return list(self._results)


class _FakeAnonymizer:
    def __init__(self) -> None:
        self.calls = 0

    def anonymize(
        self,
        text: str,
        analyzer_results: list[Any],
        operators: dict[str, Any] | None = None,
    ) -> Any:
        self.calls += 1
        return None


def test_presidio_sanitizer_replaces_matches_right_to_left() -> None:
    text = "Kartik writes to me@example.com"
    email_start = text.index("me@example.com")
    email_end = email_start + len("me@example.com")
    analyzer = _FakeAnalyzer(
        [
            _FakeMatch(entity_type="PERSON", start=0, end=6),
            _FakeMatch(
                entity_type="EMAIL_ADDRESS",
                start=email_start,
                end=email_end,
            ),
        ],
    )
    anonymizer = _FakeAnonymizer()
    sanitizer = PresidioSanitizer(analyzer=analyzer, anonymizer=anonymizer)
    result = sanitizer.sanitize(text)
    assert "<PERSON_0>" in result.text
    assert "<EMAIL_ADDRESS_0>" in result.text
    assert result.counts_by_kind == {"PERSON": 1, "EMAIL_ADDRESS": 1}
    assert "Kartik" not in result.text
    assert "me@example.com" not in result.text
    assert analyzer.calls == 1
    assert anonymizer.calls == 1


def test_presidio_sanitizer_no_results_returns_input() -> None:
    sanitizer = PresidioSanitizer(
        analyzer=_FakeAnalyzer([]),
        anonymizer=_FakeAnonymizer(),
    )
    result = sanitizer.sanitize("nothing to redact")
    assert result.text == "nothing to redact"
    assert result.counts_by_kind == {}


@pytest.mark.skipif(
    os.environ.get("PRESIDIO_LIVE") != "1",
    reason="requires real Presidio model load",
)
def test_presidio_sanitizer_live_load() -> None:  # pragma: no cover — opt-in
    sanitizer = PresidioSanitizer()
    result = sanitizer.sanitize("Alice mailed bob@example.com from Paris")
    # Coverage of the real model output is intentionally loose; the
    # smoke test is that *something* came back.
    assert "Alice" not in result.text or "bob@example.com" not in result.text


# ----------------------------------------------------------------------
# SanitizerChain (Phase 4)
# ----------------------------------------------------------------------


class _StubSanitizer:
    def __init__(self, *, kind: str, replacement: str) -> None:
        self.kind = kind
        self.replacement = replacement

    def sanitize(self, text: str) -> RedactionResult:
        if self.kind not in text:
            return RedactionResult(text=text)
        return RedactionResult(
            text=text.replace(self.kind, self.replacement),
            reversal_map={self.replacement: self.kind},
            counts_by_kind={self.kind: 1},
        )


def test_chain_runs_sanitizers_in_order_and_merges_counts() -> None:
    chain = SanitizerChain(
        [
            _StubSanitizer(kind="A", replacement="<A>"),
            _StubSanitizer(kind="B", replacement="<B>"),
        ],
    )
    result = chain.sanitize("AB")
    assert result.text == "<A><B>"
    assert result.counts_by_kind == {"A": 1, "B": 1}
    assert result.reversal_map == {"<A>": "A", "<B>": "B"}


def test_chain_merge_later_wins_on_collision() -> None:
    a = _StubSanitizer(kind="A", replacement="<X>")
    b = _StubSanitizer(kind="<X>", replacement="<X>")  # rewrites placeholder

    class _OverwriteSanitizer:
        def sanitize(self, text: str) -> RedactionResult:
            return RedactionResult(
                text=text,
                reversal_map={"<X>": "from-second-pass"},
                counts_by_kind={"X": 2},
            )

    chain = SanitizerChain([a, _OverwriteSanitizer()])
    _ = b  # silence lint
    result = chain.sanitize("A")
    assert result.reversal_map["<X>"] == "from-second-pass"
    assert result.counts_by_kind["A"] == 1
    assert result.counts_by_kind["X"] == 2


# ----------------------------------------------------------------------
# build_default_chain (Phase 4 / Phase 7)
# ----------------------------------------------------------------------


def test_build_default_chain_disables_presidio() -> None:
    chain = build_default_chain(
        user_email="me@example.com",
        presidio_enabled=False,
    )
    assert all(not isinstance(s, PresidioSanitizer) for s in chain.sanitizers)


def test_build_default_chain_skips_identity_when_no_envs() -> None:
    chain = build_default_chain(presidio_enabled=False)
    assert all(not isinstance(s, IdentityScrubber) for s in chain.sanitizers)


def test_protocol_runtime_check() -> None:
    assert isinstance(RegexSanitizer(), Sanitizer)
    assert isinstance(
        IdentityScrubber({"<USER_EMAIL>": ["me@example.com"]}),
        Sanitizer,
    )
