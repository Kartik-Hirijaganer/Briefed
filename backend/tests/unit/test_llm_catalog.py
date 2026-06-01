"""Unit tests for :mod:`app.llm.catalog` (Track A Phase 2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.llm import catalog


def test_resolve_returns_known_entry() -> None:
    entry = catalog.resolve("gemini-flash")
    assert entry["openrouter_id"] == "google/gemini-2.0-flash-001"
    assert entry["max_output_tokens"] >= 1


def test_resolve_unknown_name_raises() -> None:
    with pytest.raises(catalog.UnknownModelError):
        catalog.resolve("not-a-model")


def test_unknown_model_error_is_keyerror_subclass() -> None:
    # callers can still `except KeyError` if they prefer.
    with pytest.raises(KeyError):
        catalog.resolve("nope")


def test_primary_and_fallbacks_resolve() -> None:
    catalog.resolve(catalog.PRIMARY)
    for name in catalog.FALLBACKS:
        catalog.resolve(name)


def test_chain_is_primary_then_fallbacks() -> None:
    assert catalog.chain()[0] == catalog.PRIMARY
    assert catalog.chain()[1:] == catalog.FALLBACKS


def test_default_catalog_loads_from_yaml() -> None:
    loaded = catalog.load_model_catalog(catalog.default_model_catalog_path())

    assert loaded.primary == catalog.PRIMARY
    assert list(loaded.fallbacks) == catalog.FALLBACKS
    assert loaded.models["claude-haiku"].daily_call_cap == 100


def test_model_entry_is_frozen() -> None:
    entry = catalog.resolve("gemini-flash")
    with pytest.raises(ValidationError):
        entry.max_output_tokens = 1


def test_catalog_rejects_missing_primary(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yml"
    path.write_text(
        """
models:
  gemini-flash:
    openrouter_id: google/gemini-2.0-flash-001
    cost_per_m_input_usd: 0.10
    cost_per_m_output_usd: 0.40
    daily_call_cap: null
    max_output_tokens: 8192
primary: missing-model
fallbacks: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(catalog.CatalogConfigError):
        catalog.load_model_catalog(path)


def test_catalog_rejects_unknown_fallback(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yml"
    path.write_text(
        """
models:
  gemini-flash:
    openrouter_id: google/gemini-2.0-flash-001
    cost_per_m_input_usd: 0.10
    cost_per_m_output_usd: 0.40
    daily_call_cap: null
    max_output_tokens: 8192
primary: gemini-flash
fallbacks:
  - missing-model
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(catalog.CatalogConfigError):
        catalog.load_model_catalog(path)


def test_catalog_rejects_malformed_file(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yml"
    path.write_text("- not-a-mapping\n", encoding="utf-8")

    with pytest.raises(catalog.CatalogConfigError):
        catalog.load_model_catalog(path)
