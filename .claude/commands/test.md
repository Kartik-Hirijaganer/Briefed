---
description: Run the full Briefed test suite — Python (pytest) and React (vitest).
argument-hint: "[py|react|all] (default: all)"
allowed-tools: Bash(make:*), Bash(python:*), Bash(pytest:*), Bash(npm:*), Bash(cd:*), Read
---

# /test — Run all tests (Python + React)

Run both test suites and report a unified summary via the canonical Make
target. Default scope is `all`; if `$ARGUMENTS` is `py` run only Python,
if `react` run only the frontend.

## All suites

```bash
make test
```

The unified summary is printed by `backend/scripts/test_summary.py`,
which reads JSON artifacts from `.artifacts/`. Exit code is non-zero
if any suite failed.

## Python only

```bash
pytest -m "not e2e and not eval" --cov=backend/app --cov-report=term-missing
```

## React only

```bash
npm --prefix frontend run test -- --reporter=verbose
```

## Execution order

When scope is `all`, prefer `make test`. It runs both suites and
consolidates the result. If the user wants raw per-suite output, run the
individual commands in parallel via two simultaneous `Bash` tool calls.

## Output format

The summary renderer produces a compact table:

```
 pytest         342 passed    2 failed    0 skipped    18.4s
 vitest         187 passed    0 failed    3 skipped     6.1s
 playwright     (skipped — artifact missing)
 promptfoo      (skipped — artifact missing)

 Exit code: 1
```

On failure, show the first failing test's output verbatim and name the
file:line where it failed. Do **not** attempt to auto-fix failures unless
the user asks — just report.
