"""Unified pass/fail summary across pytest + vitest + playwright + promptfoo.

Reads JSON report artifacts written by `make test` into `.artifacts/` and
prints a human-readable table. Exits non-zero if any suite failed so the
Make target surfaces the failure to CI.

Designed to be robust when a suite didn't run: missing JSON files are
reported as "skipped" rather than "failed".
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = REPO_ROOT / ".artifacts"


@dataclass(frozen=True)
class SuiteResult:
    """One suite's roll-up counts."""

    name: str
    passed: int
    failed: int
    skipped: int
    duration_s: float | None
    ran: bool


def _load_pytest() -> SuiteResult:
    """Load the pytest JSON report if present."""
    path = ARTIFACTS / "pytest.json"
    if not path.is_file():
        return SuiteResult("pytest", 0, 0, 0, None, ran=False)

    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    return SuiteResult(
        name="pytest",
        passed=int(summary.get("passed", 0)),
        failed=int(summary.get("failed", 0)) + int(summary.get("error", 0)),
        skipped=int(summary.get("skipped", 0)),
        duration_s=float(data.get("duration", 0.0)) or None,
        ran=True,
    )


def _load_vitest() -> SuiteResult:
    """Load the vitest JSON report if present."""
    path = ARTIFACTS / "vitest.json"
    if not path.is_file():
        return SuiteResult("vitest", 0, 0, 0, None, ran=False)

    data = json.loads(path.read_text(encoding="utf-8"))
    passed = int(data.get("numPassedTests", 0))
    failed = int(data.get("numFailedTests", 0))
    skipped = int(data.get("numPendingTests", 0)) + int(data.get("numTodoTests", 0))
    start_time = data.get("startTime")
    end_time = data.get("endTime")
    duration = None
    if isinstance(start_time, (int, float)) and isinstance(end_time, (int, float)):
        duration = (float(end_time) - float(start_time)) / 1000.0
    return SuiteResult("vitest", passed, failed, skipped, duration, ran=True)


def _load_playwright() -> SuiteResult:
    """Load the playwright JSON report if present."""
    path = ARTIFACTS / "playwright.json"
    if not path.is_file():
        return SuiteResult("playwright", 0, 0, 0, None, ran=False)

    data = json.loads(path.read_text(encoding="utf-8"))
    stats = data.get("stats", {})
    return SuiteResult(
        name="playwright",
        passed=int(stats.get("expected", 0)),
        failed=int(stats.get("unexpected", 0)),
        skipped=int(stats.get("skipped", 0)),
        duration_s=float(stats.get("duration", 0.0)) / 1000.0 if stats else None,
        ran=True,
    )


def _load_promptfoo() -> SuiteResult:
    """Load the promptfoo JSON report if present."""
    path = ARTIFACTS / "promptfoo.json"
    if not path.is_file():
        return SuiteResult("promptfoo", 0, 0, 0, None, ran=False)

    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results", {})
    stats = results.get("stats", {})
    return SuiteResult(
        name="promptfoo",
        passed=int(stats.get("successes", 0)),
        failed=int(stats.get("failures", 0)),
        skipped=0,
        duration_s=None,
        ran=True,
    )


def _format_row(suite: SuiteResult) -> str:
    """Format one suite row for the summary table."""
    if not suite.ran:
        return f" {suite.name:12s} (skipped — artifact missing)"

    duration = f"{suite.duration_s:6.1f}s" if suite.duration_s is not None else "    —"
    return (
        f" {suite.name:12s} {suite.passed:4d} passed   "
        f"{suite.failed:4d} failed   {suite.skipped:4d} skipped   {duration}"
    )


def main() -> int:
    """Print the summary and return a shell exit code."""
    suites = [_load_pytest(), _load_vitest(), _load_playwright(), _load_promptfoo()]

    bar = "━" * 60
    print(bar)
    print(" Briefed test summary")
    print(bar)
    for suite in suites:
        print(_format_row(suite))

    any_failures = any(s.failed > 0 for s in suites)
    ran_count = sum(1 for s in suites if s.ran)
    if ran_count == 0:
        print("\n No suite results were produced — did `make test` run the runners?")
        return 2

    exit_code = 1 if any_failures else 0
    print()
    print(f" Exit code: {exit_code}")
    print(bar)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
