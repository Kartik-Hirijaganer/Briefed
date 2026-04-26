"""Unit tests for :class:`PromptRegistry` (plan §14 Phase 2)."""

from __future__ import annotations

import pytest

from app.services.prompts.registry import (
    PromptBundleError,
    PromptRegistry,
    default_prompt_root,
)


def _write(tmp_path, name, version, body="body text"):
    dir_ = tmp_path / name
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"v{version}.md"
    path.write_text(
        f"---\nid: {name}\nversion: {version}\nmodel: gemini-1.5-flash\n"
        f"temperature: 0.0\nmax_tokens: 400\n---\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_load_single_prompt(tmp_path) -> None:
    _write(tmp_path, "triage", 1)
    registry = PromptRegistry.load(tmp_path)
    entry = registry.get("triage", version=1)
    assert entry.spec.name == "triage"
    assert entry.spec.version == 1
    assert entry.content_hash != b""
    assert entry.spec.model == "gemini-1.5-flash"


def test_latest_picks_highest_version(tmp_path) -> None:
    _write(tmp_path, "triage", 1, body="alpha")
    _write(tmp_path, "triage", 2, body="beta")
    registry = PromptRegistry.load(tmp_path)
    assert registry.latest("triage").spec.version == 2


def test_duplicate_versions_raise(tmp_path) -> None:
    dir_ = tmp_path / "triage"
    dir_.mkdir()
    (dir_ / "v1.md").write_text(
        "---\nid: triage\nversion: 1\nmodel: g\ntemperature: 0\nmax_tokens: 1\n---\na",
        encoding="utf-8",
    )
    (dir_ / "v1b.md").write_text(
        "---\nid: triage\nversion: 1\nmodel: g\ntemperature: 0\nmax_tokens: 1\n---\nb",
        encoding="utf-8",
    )
    with pytest.raises(PromptBundleError):
        PromptRegistry.load(tmp_path, include_globs=("*/v*.md",))


def test_missing_frontmatter_raises(tmp_path) -> None:
    path = tmp_path / "triage" / "v1.md"
    path.parent.mkdir()
    path.write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(PromptBundleError):
        PromptRegistry.load(tmp_path)


def test_missing_required_key_raises(tmp_path) -> None:
    path = tmp_path / "triage" / "v1.md"
    path.parent.mkdir()
    path.write_text(
        "---\nid: triage\nversion: 1\n---\nbody",
        encoding="utf-8",
    )
    with pytest.raises(PromptBundleError):
        PromptRegistry.load(tmp_path)


def test_empty_registry_raises(tmp_path) -> None:
    with pytest.raises(PromptBundleError):
        PromptRegistry.load(tmp_path)


def test_default_prompt_root_exists() -> None:
    # The real packages/prompts/triage/v1.md shipped with this repo.
    registry = PromptRegistry.load(default_prompt_root())
    assert registry.get("triage", version=1).spec.model.startswith("gemini")
