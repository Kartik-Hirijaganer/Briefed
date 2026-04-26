"""Schema sanity for the Phase 8 adversarial prompt-injection fixtures.

The full Promptfoo run hits live LLMs and is gated behind ``EVAL=1``.
This cheap sister check loads the JSONL files at every CI run so a
malformed entry (missing ``vars``, missing ``expected``, JSON typo)
fails fast inside the unit suite per plan §19.11 Phase 8.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "eval" / "golden"


def _load(name: str) -> list[dict[str, object]]:
    """Return the parsed JSONL fixtures for ``name``."""
    path = _FIXTURE_DIR / name
    entries: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        entries.append(json.loads(stripped))
    return entries


@pytest.mark.parametrize(
    "fixture_file",
    [
        "triage_v1_adversarial.jsonl",
        "summarize_relevant_v1_adversarial.jsonl",
        "job_extract_v1_adversarial.jsonl",
    ],
)
def test_adversarial_fixtures_well_formed(fixture_file: str) -> None:
    """Every adversarial entry has ``vars`` + ``expected`` blocks."""
    entries = _load(fixture_file)
    assert entries, f"empty fixture file {fixture_file}"
    for idx, entry in enumerate(entries):
        assert "vars" in entry, f"{fixture_file}[{idx}] missing vars"
        assert "expected" in entry, f"{fixture_file}[{idx}] missing expected"
        vars_block = entry["vars"]
        assert isinstance(vars_block, dict)
        # The injection must arrive via ``plain_text_excerpt`` so the
        # ``<untrusted_email>`` delimiter wraps it; reject fixtures that
        # accidentally hide the payload elsewhere.
        excerpt = vars_block.get("plain_text_excerpt", "")
        assert isinstance(excerpt, str) and excerpt, (
            f"{fixture_file}[{idx}] missing plain_text_excerpt body"
        )


def test_summarize_adversarial_fixtures_target_known_attacks() -> None:
    """Summarize adversarial set covers the Phase 8 attack catalog."""
    entries = _load("summarize_relevant_v1_adversarial.jsonl")
    bodies = "\n".join(str(e["vars"]["plain_text_excerpt"]) for e in entries)
    assert "</untrusted_email>" in bodies, "delimiter break-out attack missing"
    assert "<prompt>" in bodies or "[INSTRUCTIONS_FOR_THE_AI]" in bodies, (
        "fake-system-instruction attack missing"
    )
    assert "Ignore previous instructions" in bodies, "instruction-override attack missing"


def test_job_adversarial_fixtures_target_known_attacks() -> None:
    """Jobs adversarial set covers the Phase 8 attack catalog."""
    entries = _load("job_extract_v1_adversarial.jsonl")
    bodies = "\n".join(str(e["vars"]["plain_text_excerpt"]) for e in entries)
    assert "</untrusted_email>" in bodies, "delimiter break-out attack missing"
    assert "<prompt>" in bodies or "[SYSTEM_INSTRUCTION]" in bodies, (
        "fake-system-instruction attack missing"
    )
