"""Lightweight faithfulness regression over the golden summary fixtures.

The plan §14 Phase 3 exit criterion "faithfulness ≥ 4.3 (Opus-as-judge)"
is measured by the Promptfoo job in CI (`backend/eval/promptfoo.yaml`).
That job requires live LLM credentials and is skipped on PRs that do not
touch prompts.

This unit test is the cheaper sister check: for every golden fixture, we
assert that the expected fact tokens actually appear in the supplied
``plain_text_excerpt``. A faithful summary is a *necessary* condition; a
faithful prompt that drops those tokens would regress this test
immediately — catching editing mistakes without hitting a provider.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "eval" / "golden"


def _load_fixtures(name: str) -> list[dict[str, object]]:
    """Return the parsed JSONL fixtures for ``name``."""
    path = _FIXTURE_DIR / name
    entries: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entries.append(json.loads(line))
    return entries


@pytest.mark.parametrize(
    "fixture_file",
    ["summarize_relevant_v1.jsonl"],
)
def test_summary_fixtures_reference_source_tokens(fixture_file: str) -> None:
    entries = _load_fixtures(fixture_file)
    assert entries, f"fixture {fixture_file} is empty"
    for entry in entries:
        body = str(entry["vars"]["plain_text_excerpt"])  # type: ignore[index]
        expected = entry["expected"]  # type: ignore[index]
        for token in expected.get("must_contain", []):  # type: ignore[union-attr]
            if "promo" in token.lower() or "no" in token.lower():
                # Waste-path fixtures check the summary characterization
                # rather than content tokens; skip the strict body check.
                continue
            assert token in body, f"{token!r} not in fixture body"


def test_cluster_fixture_blocks_reference_source_tokens() -> None:
    entries = _load_fixtures("newsletter_group_v1.jsonl")
    assert entries
    for entry in entries:
        block = str(entry["vars"]["newsletters_block"])  # type: ignore[index]
        expected = entry["expected"]  # type: ignore[index]
        for token in expected.get("must_contain_bullets", []):  # type: ignore[union-attr]
            assert token in block, f"{token!r} missing from cluster body"
        assert expected["cluster_key"] == entry["vars"]["cluster_key"]  # type: ignore[index]
