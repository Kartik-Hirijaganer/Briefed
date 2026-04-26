"""Unit tests for ``backend/scripts/write_release_metadata.py`` helpers.

Covers the pure-functional artifact-id detectors so a deploy that
produces an unexpected hash (broken OpenAPI export, missing prompt
file) fails before it writes a misleading ``release_metadata`` row.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # pragma: no cover
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "backend" / "scripts"


@pytest.fixture()
def release_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the deploy script with REPO_ROOT pointing at the live repo."""
    if str(SCRIPTS_DIR) not in sys.path:
        monkeypatch.syspath_prepend(str(SCRIPTS_DIR))
    module = importlib.import_module("write_release_metadata")
    return importlib.reload(module)


def test_semver_strips_leading_v(release_module: ModuleType) -> None:
    assert release_module._semver("v1.2.3") == "1.2.3"
    assert release_module._semver("1.2.3") == "1.2.3"
    assert release_module._semver("  v0.0.1  ") == "0.0.1"


def test_detect_alembic_head_returns_latest_revision(
    release_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_init.py").write_text('revision: str = "0001"\n')
    (versions / "0002_more.py").write_text('revision: str = "0002"\n')
    (versions / "0010_phase9.py").write_text('revision: str = "0010"\n')

    monkeypatch.setattr(release_module, "ALEMBIC_VERSIONS_DIR", versions)
    assert release_module.detect_alembic_head() == "0010"


def test_detect_alembic_head_raises_when_empty(
    release_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_module, "ALEMBIC_VERSIONS_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="No Alembic revisions"):
        release_module.detect_alembic_head()


def test_detect_api_schema_version_reads_openapi(
    release_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = tmp_path / "openapi.json"
    spec.write_text(json.dumps({"info": {"version": "1.0.0"}}))
    monkeypatch.setattr(release_module, "OPENAPI_PATH", spec)
    assert release_module.detect_api_schema_version() == "1.0.0"


def test_detect_api_schema_version_rejects_empty(
    release_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = tmp_path / "openapi.json"
    spec.write_text(json.dumps({"info": {}}))
    monkeypatch.setattr(release_module, "OPENAPI_PATH", spec)
    with pytest.raises(RuntimeError, match=r"info\.version"):
        release_module.detect_api_schema_version()


def test_detect_prompt_bundle_version_is_stable(
    release_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = tmp_path / "prompts"
    (prompts / "triage").mkdir(parents=True)
    (prompts / "schemas").mkdir()
    (prompts / "triage" / "v1.md").write_text("triage v1 body")
    (prompts / "schemas" / "triage.v1.json").write_text("{}")

    monkeypatch.setattr(release_module, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(release_module, "REPO_ROOT", tmp_path)
    first = release_module.detect_prompt_bundle_version()
    second = release_module.detect_prompt_bundle_version()
    assert first == second
    assert len(first) == 16


def test_detect_prompt_bundle_version_changes_on_edit(
    release_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = tmp_path / "prompts"
    (prompts / "triage").mkdir(parents=True)
    (prompts / "schemas").mkdir()
    target = prompts / "triage" / "v1.md"
    target.write_text("first")
    monkeypatch.setattr(release_module, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(release_module, "REPO_ROOT", tmp_path)
    before = release_module.detect_prompt_bundle_version()

    target.write_text("second — body changed")
    after = release_module.detect_prompt_bundle_version()
    assert before != after


def test_detect_frontend_build_id_returns_none_without_dist(
    release_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_module, "FRONTEND_DIST_DIR", tmp_path / "missing")
    assert release_module.detect_frontend_build_id() is None


def test_detect_frontend_build_id_hashes_dist(
    release_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    monkeypatch.setattr(release_module, "FRONTEND_DIST_DIR", dist)
    fid = release_module.detect_frontend_build_id()
    assert fid is not None
    assert len(fid) == 16
