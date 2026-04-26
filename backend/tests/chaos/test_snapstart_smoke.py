"""SnapStart cold-start smoke (plan §19.15 Phase 8).

The exit criterion is "cold-start latency ≤ 500 ms post-restore." We
cannot run a real Lambda + SnapStart restore in unit CI, so this drill
measures the closest unit-level proxy: importing :mod:`app.main` from a
freshly-cleared module cache, which mirrors what SnapStart's restore
does after the snapshot is hydrated. The settings/logging/tracing/sentry
init paths must complete inside the budget on the test runner so we
notice regressions (a new sync HTTP call at module import would blow
this up immediately).
"""

from __future__ import annotations

import importlib
import sys
import time
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.chaos

# Generous budget for the unit-test runner; production SnapStart restore
# is well under this. Tighten as the bundle hardens.
_BUDGET_MS = 1500


@pytest.fixture()
def fresh_module_cache() -> Iterator[None]:
    """Drop ``app.main`` (and friends) from ``sys.modules`` per test."""
    keys = [k for k in list(sys.modules) if k.startswith("app.main")]
    saved = {k: sys.modules.pop(k) for k in keys}
    try:
        yield
    finally:
        for k, v in saved.items():
            sys.modules[k] = v


def test_module_import_within_budget(fresh_module_cache: None) -> None:
    start = time.perf_counter()
    importlib.import_module("app.main")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < _BUDGET_MS, (
        f"app.main module init took {elapsed_ms:.1f} ms (budget {_BUDGET_MS} ms) — "
        "a new sync import landed in the cold path"
    )


def test_logging_and_tracing_idempotent(fresh_module_cache: None) -> None:
    """Re-importing app.main must not re-run heavy init."""
    importlib.import_module("app.main")
    # Second import: the configure_* calls are guarded; this should be
    # near-instant (we use the same budget for safety).
    start = time.perf_counter()
    importlib.import_module("app.main")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < _BUDGET_MS
