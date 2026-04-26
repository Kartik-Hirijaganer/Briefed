# Contributors

Welcome. If you want to run or hack on Briefed, start here.

## Getting the code running locally

See the root [CONTRIBUTING.md](../../CONTRIBUTING.md). Short version:

```bash
make bootstrap     # installs Python + Node deps, starts docker-compose services
make dev           # runs backend + frontend in parallel with hot-reload
```

## Codebase map

```
backend/        FastAPI + workers (Python 3.11+)
frontend/       React PWA (Vite + TypeScript)
packages/       Shared contracts / prompts / config schemas / UI primitives
infra/terraform Deployable infrastructure
docs/           ADRs + architecture + operations + security
tests/          Cross-service e2e / integration (backend-only unit tests live in backend/tests/)
```

## Standards

- Python: Google docstrings, full type hints, Pydantic for every payload.
  Lint via Ruff; type-check via `mypy --strict`. See [CLAUDE.md](../../CLAUDE.md).
- TypeScript: Google-style JSDoc on every exported symbol, strict TS, named
  exports. Lint via ESLint; format via Prettier.
- Commits: Conventional Commits (`feat:`, `fix:`, `refactor:`, `chore:`, …).
- Branches: feature branches; PRs into `main`; never push directly to main.

## Documentation

- Every decision worth revisiting in six months belongs in an ADR
  (`docs/adr/`).
- User-visible changes update the root `README.md` and `CHANGELOG.md`.
- Prompt changes land under `packages/prompts/` with a Promptfoo diff.
