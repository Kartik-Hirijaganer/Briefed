# tests/

Cross-service tests that span backend + frontend (or don't belong to either
exclusively). Backend-only unit tests live under `backend/tests/unit/`;
backend-only integration tests under `backend/tests/integration/`.

## Layout

```
tests/
├── e2e/                # Playwright specs — login, OAuth, dashboard render, etc.
├── fixtures/           # shared MIME bundles, OpenAPI golden snapshots, etc.
└── prompt-evals/       # Promptfoo configs + datasets (symlinked from packages/prompts)
```

Phase 0 ships only `e2e/`. Fixtures + prompt-evals land alongside the
phases that need them (Phase 1 fixtures, Phase 2 evals).
