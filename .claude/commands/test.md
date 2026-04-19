---
description: Run the full Briefed test suite — Python (pytest) and React (vitest).
argument-hint: "[py|react|all] (default: all)"
allowed-tools: Bash(python:*), Bash(pytest:*), Bash(npm:*), Bash(cd:*), Read
---

# /test — Run all tests (Python + React)

Run both test suites and report a unified summary. Default scope is `all`; if `$ARGUMENTS` is `py` run only Python, if `react` run only the frontend.

## Python (backend)

```bash
cd backend && pytest -ra --cov=app --cov-report=term-missing
```

Expected: exit code 0. Report passed / failed / skipped counts and coverage %.

## React (frontend)

```bash
cd frontend && npm test -- --reporter=verbose
```

Expected: exit code 0. Report suites / tests / duration.

## Execution order

Run the two suites **in parallel** via two simultaneous `Bash` tool calls (independent, no shared state). If one fails, still report the other's result — do not short-circuit.

## Output format

```
Python  : ✅ 42 passed, 0 failed  (coverage 87%)
React   : ✅ 18 passed, 0 failed  (1.2s)
Overall : PASS
```

On failure, show the first failing test's output verbatim and name the file:line where it failed. Do **not** attempt to auto-fix failures unless the user asks — just report.
