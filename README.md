# Briefed

Personal AI email agent that runs a daily pipeline on your Gmail inbox. Uses the Claude API for categorization, priority scoring, and tech-news summarization. React PWA dashboard — works on desktop and mobile.

**Stack:** Python · FastAPI · Pydantic · Claude API · Gmail API · Supabase · React · TypeScript · Vite · PWA

**Version:** 1.0.0

---

## Project layout

```
.
├── backend/          FastAPI service (Python 3.11+), Claude + Gmail + Supabase
├── frontend/         React PWA dashboard (Vite + TypeScript)
├── .claude/          Claude Code config — slash commands & plans
│   ├── commands/     /make-docs, /test
│   └── plans/        implementation plans (YYYY-MM-DD-slug.md)
├── CLAUDE.md         project rules for Claude Code
└── pyproject.toml    Python tooling (ruff, mypy, pytest)
```

## Getting started

### Backend

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate        # on Windows; use `source .venv/bin/activate` on *nix
pip install -e ".[dev]"         # installs from repo-root pyproject.toml
uvicorn app.main:app --reload
```

Swagger UI: http://localhost:8000/docs · ReDoc: http://localhost:8000/redoc

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Developer commands

| Command             | What it does                                                    |
|---------------------|-----------------------------------------------------------------|
| `/make-docs`        | Regenerate the Swagger/OpenAPI spec (pinned to v1.0.0).         |
| `/test`             | Run Python (`pytest`) and React (`vitest`) suites in parallel.  |
| `ruff check backend`| Lint Python (Google docstrings + type annotations enforced).    |
| `ruff format backend` | Format Python.                                                |
| `mypy`              | Strict type-check Python.                                       |
| `npm run lint`      | Lint TS/TSX (Google style + JSDoc enforced).                    |
| `npm run format`    | Prettier-format frontend.                                       |

## Coding standards

Enforced by tooling and documented in [CLAUDE.md](CLAUDE.md):

- **Python** — Google-style docstrings, full type hints, Pydantic for all structured data. Lint via Ruff; type-check via `mypy --strict`.
- **React / TS** — Google-style JSDoc on every exported symbol, strict TS, named exports. Lint via ESLint (`eslint-config-google` + `jsdoc` plugin); format via Prettier.

## Git workflow

- Feature branches; PRs into `main`.
- Claude never pushes to any remote without explicit permission.
- Claude never pushes / merges to `main` without explicit permission.

See [CLAUDE.md](CLAUDE.md) for the full rule set.
