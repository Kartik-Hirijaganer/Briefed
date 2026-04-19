# packages/

Shared code hoisted out of `backend/` and `frontend/` to keep contracts, prompts,
config schemas, and UI tokens from drifting between them. Layout per plan §19.2.

| Package     | Purpose                                                             |
|-------------|---------------------------------------------------------------------|
| `contracts` | OpenAPI spec + generated TypeScript client types (drift-gated).     |
| `prompts`   | Versioned LLM prompt bundles + JSON schemas for tool-use outputs.   |
| `config`    | Seed defaults, sample policies, JSON Schemas derived from Pydantic. |
| `ui`        | Design tokens + reusable React primitives (imported by frontend).   |

Cross-package rules:
- The OpenAPI spec is the single source of truth for request/response shapes —
  `make docs` regenerates `packages/contracts/openapi.json` and the TS client;
  `git diff --exit-code` in CI fails the PR on drift.
- Prompt bundles are immutable once published — new prompt versions land as new
  files (`v1.md`, `v2.md`), never in-place edits. `packages/prompts/README.md`
  covers the version contract.
- `packages/ui` is consumed by `frontend/` as an npm workspace (Vite alias).
- Nothing in `packages/` may import from `backend/` or `frontend/`.
