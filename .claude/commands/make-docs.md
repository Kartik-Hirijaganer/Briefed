---
description: Generate the Swagger / OpenAPI spec for the Briefed FastAPI app, pinned to release version 1.0.0.
argument-hint: "[--version <x.y.z>]"
allowed-tools: Bash(python:*), Bash(uvicorn:*), Read, Edit, Write
---

# /make-docs — Generate Swagger / OpenAPI documentation

You are generating the API documentation for Briefed. The spec lives alongside the app; clients consume it via the FastAPI-served UI and the checked-in static spec.

## Release version

Pin the release version to **`1.0.0`** unless the user passed `--version <x.y.z>` in `$ARGUMENTS`, in which case use that value.

## Steps

1. **Verify the version is consistent** across:
   - [backend/app/__init__.py](../../backend/app/__init__.py) — `__version__`
   - [pyproject.toml](../../pyproject.toml) — `[project].version`
   - [frontend/package.json](../../frontend/package.json) — `version`

   If any of these disagree with the target release version, update them to match (this is the source of truth that flows into `app.openapi()["info"]["version"]`).

2. **Regenerate the OpenAPI JSON** by running the export script:

   ```bash
   cd backend && python -m scripts.export_openapi
   ```

   This writes `docs/openapi.json` at the repo root with `info.version` pinned to the release version.

3. **Verify** the emitted spec:
   - `docs/openapi.json` exists and is valid JSON.
   - `info.version` equals the target release version.
   - `info.title` is `"Briefed API"`.
   - Every route in `backend/app/` is represented (spot-check by counting `paths`).

4. **Remind the user** that the live, interactive Swagger UI is available at `http://localhost:8000/docs` and ReDoc at `http://localhost:8000/redoc` when the dev server runs (`uvicorn app.main:app --reload` from `backend/`).

5. **Do NOT commit or push.** Per [CLAUDE.md](../../CLAUDE.md) §4, only commit when the user says so, and never push without explicit permission.

## Output

Report back:
- The release version written.
- The path to the emitted spec.
- Path count and a one-line summary (e.g. "12 paths across 4 tags").
- Any version mismatches you fixed.
