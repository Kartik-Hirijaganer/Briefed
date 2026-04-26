# Briefed

Personal AI email agent that runs a daily pipeline on your Gmail inbox.
Summarizes what matters, extracts job matches, and recommends what to
unsubscribe from — never acts without your say-so (ADR 0006). React PWA
dashboard; works on desktop and mobile.

**Stack:** Python · FastAPI · Pydantic · OpenRouter (Gemini Flash +
Claude Haiku 4.5 routes per ADR 0009) · Gmail API · Supabase · React ·
TypeScript · Vite · PWA · AWS Lambda + SnapStart · Terraform

**Version:** 1.0.0 — released 2026-04-25 ([release notes](docs/release/v1.0.0.md))

---

## Project layout

```
.
├── backend/            FastAPI service + Lambda handlers + Dockerfile (Python 3.11+)
│   ├── app/            Application code (api, core, db, domain, services, workers, …)
│   ├── alembic/        SQLAlchemy migrations (Phase 1–5 schema)
│   ├── eval/           Promptfoo config + golden set + thresholds
│   └── tests/          unit/ + integration/ test suites
├── frontend/           React PWA dashboard (Vite + TypeScript)
├── packages/           Shared contracts / prompts / config / UI primitives
│   ├── contracts/      OpenAPI source of truth + provider types
│   ├── prompts/        Versioned LLM prompt bundles + JSON Schemas
│   ├── config/         Seed defaults + sample policies + generated schemas
│   └── ui/             Design tokens + reusable React primitives
├── infra/terraform/    Lambda + SnapStart + SQS + SSM + S3 + CloudFront +
│                       Route 53 + ACM + two customer-managed KMS CMKs
├── docs/
│   ├── adr/            Architecture Decision Records (0001–0008)
│   ├── architecture/   Data model, pipeline, system diagrams
│   ├── operations/     Runbook, alarms, restore + rollback drills
│   ├── release/        Release notes + announcement drafts
│   ├── security/       SECURITY.md + threat model
│   └── contributors/   Getting-started for contributors
├── tests/              Cross-service e2e + fixtures + prompt-evals
├── .claude/            Claude Code config (commands, plans)
├── .github/            Workflows, CODEOWNERS, PR + issue templates
├── CLAUDE.md           Project rules for Claude Code
├── CHANGELOG.md        Keep-a-Changelog history
├── CONTRIBUTING.md     How to contribute
├── Makefile            Canonical developer commands
├── docker-compose.yml  Local Postgres + LocalStack
└── pyproject.toml      Python tooling (ruff, mypy, pytest, coverage)
```

## Getting started

Prereqs: **Python 3.11+**, **Node 20+**, **Docker**, **Make**.

```bash
git clone https://github.com/Kartik-Hirijaganer/Briefed.git
cd Briefed
cp .env.example .env        # fill in BRIEFED_OPENROUTER_API_KEY + OAuth creds; other values optional
make bootstrap              # installs deps, starts docker-compose services
make migrate                # apply all Alembic migrations (Phase 1–4)
make dev                    # backend on :8000, frontend on :5173
```

The frontend is an npm workspace — `make bootstrap` runs `npm install` at
the repo root, which hoists deps across `frontend/` and `packages/{ui,contracts}`.
The Vite dev server proxies `/api` + `/oauth` to the local FastAPI instance
so cookies + CSRF are same-origin.

Swagger UI: http://localhost:8000/docs · ReDoc: http://localhost:8000/redoc · PWA: http://localhost:5173

## Developer commands

All canonical commands live in the top-level [Makefile](Makefile). CI
calls the same targets — there is one source of truth.

| Command              | What it does                                                           |
|----------------------|------------------------------------------------------------------------|
| `make bootstrap`     | Install Python + Node deps; start docker-compose services.             |
| `make dev`           | Run backend + frontend with hot-reload (Postgres via docker-compose).  |
| `make test`          | Run pytest + vitest and print a unified summary.                       |
| `make lint`          | Ruff + mypy + ESLint + Prettier check.                                 |
| `make coverage`      | Enforce the 80% line-coverage floor (plan §20.1).                      |
| `make docs`          | Regenerate `packages/contracts/openapi.json` + frontend TS client.     |
| `make e2e`           | Playwright e2e (sets `PLAYWRIGHT=1`).                                  |
| `make eval`          | Promptfoo prompt evals (sets `EVAL=1`).                                |
| `make migrate`       | `alembic upgrade head`.                                                |
| `make secrets-lint`  | `gitleaks detect` full-repo scan.                                      |
| `make link-check`    | Verify every relative markdown link resolves (Phase 9 release gate).   |
| `make deploy-dev`    | `terraform apply` the dev environment (requires `IMAGE_URI=<ecr>...`). |
| `npm run codegen`    | Regenerate `frontend/src/api/schema.d.ts` from the OpenAPI contract.   |
| `/make-docs`         | Claude-Code wrapper around `make docs`.                                |
| `/test`              | Claude-Code wrapper around `make test`.                                |

## Coding standards

Enforced by tooling and documented in [CLAUDE.md](CLAUDE.md):

- **Python** — Google-style docstrings, full type hints, Pydantic for every
  structured payload. Lint via Ruff; type-check via `mypy --strict`.
- **React / TS** — Google-style JSDoc on every exported symbol, strict TS,
  named exports. Lint via ESLint (`eslint-config-google` + `jsdoc`
  plugin); format via Prettier.

## Deployment

Release 1.0.0 targets AWS Lambda + SnapStart fronted by CloudFront and
the Lambda Function URL (ADR 0003). Terraform sources live under
[infra/terraform/](infra/terraform/); see
[infra/terraform/envs/dev/README.md](infra/terraform/envs/dev/README.md)
for the bootstrap + deploy flow, and
[infra/terraform/envs/prod/README.md](infra/terraform/envs/prod/README.md)
for the production stack. Steady-state cost target is ~$8–11/month
including two customer-managed KMS CMKs (plan §20.8).

Production deploys go through the
[`deploy-prod` workflow](.github/workflows/deploy-prod.yml) — annotated
tag (`v*.*.*`) → blue/green Lambda alias swing → CloudFront
invalidation → `release_metadata` row written. Rollback is a single
`aws lambda update-alias` per function;
[`docs/operations/rollback.md`](docs/operations/rollback.md) is the
operator playbook + the rehearsal we run before every cut.

## Documentation

- [DESIGN.md](DESIGN.md) — canonical design system. Read before any UI
  change; tokens, typography, motion, contrast numbers all live here.
- [docs/adr/](docs/adr/) — the eight initial architecture decisions.
- [docs/architecture/](docs/architecture/) — system diagrams + data model.
- [docs/operations/](docs/operations/) — runbook, alarms, restore +
  rollback drills, secrets rotation.
- [docs/release/](docs/release/) — 1.0.0 release notes + announcement
  draft.
- [docs/security/](docs/security/) — SECURITY.md + threat model.

## Version bumps

The single source of truth for the app version is
[packages/contracts/version.json](packages/contracts/version.json).
Bump it in one place — backend (`backend/app/__init__.py`,
`backend/app/api/v1/frontend.py`) and frontend (Vite `__APP_VERSION__`,
`<AppVersion>`) both read from this file. After bumping, run
`make docs` (or `/make-docs`) to regenerate the OpenAPI spec with the
matching `info.version` pin.

## Git workflow

- Feature branches; PRs into `main`.
- Conventional Commits (`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`).
- Claude never pushes to any remote without explicit permission.
- Claude never pushes / merges to `main` without explicit permission.

See [CLAUDE.md](CLAUDE.md) for the full rule set.

## License

[MIT](LICENSE).
