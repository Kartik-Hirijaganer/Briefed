"""Unit tests for :class:`PromptRegistry` (plan §14 Phase 2)."""

from __future__ import annotations

import pytest

from app.services.prompts.registry import (
    USER_MESSAGE_MARKER,
    PromptBundleError,
    PromptRegistry,
    default_prompt_root,
)

_BODY = f"system rules\n{USER_MESSAGE_MARKER}\n<input>{{{{value}}}}</input>"


def _write(
    tmp_path,
    name,
    version,
    *,
    body=_BODY,
    model="gemini-flash",
    max_tokens=400,
):
    dir_ = tmp_path / name
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"v{version}.md"
    path.write_text(
        f"---\nid: {name}\nversion: {version}\nmodel: {model}\n"
        f"temperature: 0.0\nmax_tokens: {max_tokens}\n---\n{body}\n",
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
    assert entry.spec.model == "gemini-flash"


def test_body_splits_into_system_and_user_template(tmp_path) -> None:
    _write(tmp_path, "triage", 1)
    entry = PromptRegistry.load(tmp_path).get("triage", version=1)
    assert entry.spec.system == "system rules"
    assert entry.spec.content == "<input>{{value}}</input>"
    assert entry.source_text == _BODY


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("no marker at all", "exactly one"),
        (f"a\n{USER_MESSAGE_MARKER}\nb\n{USER_MESSAGE_MARKER}\nc", "exactly one"),
        (f"{USER_MESSAGE_MARKER}\n<input>{{{{value}}}}</input>", "both sides"),
        (f"system rules\n{USER_MESSAGE_MARKER}\n", "both sides"),
        (f"rules {{{{value}}}}\n{USER_MESSAGE_MARKER}\n<input/>", "placeholders"),
    ],
)
def test_malformed_body_raises(tmp_path, body, match) -> None:
    _write(tmp_path, "triage", 1, body=body)
    with pytest.raises(PromptBundleError, match=match):
        PromptRegistry.load(tmp_path)


def test_marker_inside_a_line_does_not_split(tmp_path) -> None:
    body = f"see {USER_MESSAGE_MARKER} below\n{USER_MESSAGE_MARKER}\n<input/>"
    _write(tmp_path, "triage", 1, body=body)
    entry = PromptRegistry.load(tmp_path).get("triage", version=1)
    assert entry.spec.system == f"see {USER_MESSAGE_MARKER} below"


def test_content_hash_covers_frontmatter(tmp_path) -> None:
    _write(tmp_path / "a", "triage", 1, max_tokens=400)
    _write(tmp_path / "b", "triage", 1, max_tokens=700)
    first = PromptRegistry.load(tmp_path / "a").get("triage", version=1)
    second = PromptRegistry.load(tmp_path / "b").get("triage", version=1)
    assert first.content_hash != second.content_hash


def test_latest_picks_highest_version(tmp_path) -> None:
    _write(tmp_path, "triage", 1)
    _write(tmp_path, "triage", 2)
    registry = PromptRegistry.load(tmp_path)
    assert registry.latest("triage").spec.version == 2


def test_duplicate_versions_raise(tmp_path) -> None:
    dir_ = tmp_path / "triage"
    dir_.mkdir()
    front = "---\nid: triage\nversion: 1\nmodel: gemini-flash\ntemperature: 0\nmax_tokens: 1\n---\n"
    (dir_ / "v1.md").write_text(f"{front}a\n{USER_MESSAGE_MARKER}\nx", encoding="utf-8")
    (dir_ / "v1b.md").write_text(f"{front}b\n{USER_MESSAGE_MARKER}\ny", encoding="utf-8")
    with pytest.raises(PromptBundleError, match="duplicate"):
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


def test_unknown_catalog_model_raises(tmp_path) -> None:
    _write(tmp_path, "triage", 1, model="not-a-catalog-key")

    with pytest.raises(PromptBundleError, match="unknown model"):
        PromptRegistry.load(tmp_path)


def test_default_prompt_root_exists() -> None:
    registry = PromptRegistry.load(default_prompt_root())
    assert registry.get("triage", version=2).spec.model == "gemini-flash"
    assert registry.latest("triage").spec.version == 2


def test_shipped_prompts_put_input_only_in_user_message() -> None:
    entries = PromptRegistry.load(default_prompt_root()).all()
    assert {entry.spec.name for entry in entries} == {
        "category_digest",
        "newsletter_group",
        "summarize_relevant",
        "triage",
        "unsubscribe_borderline",
    }
    for entry in entries:
        assert entry.spec.system, entry.spec.name
        assert "{{" not in entry.spec.system, entry.spec.name
        assert "{{" in entry.spec.content, entry.spec.name


def test_default_prompt_root_uses_lambda_task_root(monkeypatch, tmp_path) -> None:
    lambda_prompt_root = tmp_path / "packages" / "prompts"
    _write(lambda_prompt_root, "triage", 1)
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))

    assert default_prompt_root() == lambda_prompt_root
    registry = PromptRegistry.load()
    assert registry.get("triage", version=1).spec.name == "triage"
