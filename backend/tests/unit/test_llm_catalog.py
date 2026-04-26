"""Unit tests for :mod:`app.llm.catalog` (Track A Phase 2)."""

from __future__ import annotations

import pytest

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
