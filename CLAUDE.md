# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# Briefed — Project Rules

Personal AI email agent. Stack: Python · FastAPI · Pydantic · Gemini 1.5 Flash (primary) · Claude Haiku 4.5 (fallback) · Gmail API · Supabase · React · PWA · AWS Lambda + SnapStart · Terraform.

Monorepo layout:
- [backend/](backend/) — FastAPI + Pydantic + LLM pipeline (Python 3.11+); also hosts the Lambda handlers
- [frontend/](frontend/) — React PWA dashboard (Vite + TypeScript)
- [packages/](packages/) — shared contracts (OpenAPI), versioned prompt bundles + JSON Schemas, seed config, UI primitives
- [infra/terraform/](infra/terraform/) — Lambda + SnapStart + SQS + SSM + S3 + CloudFront + KMS CMKs
- [docs/adr/](docs/adr/) — ADRs 0001–0008 (immutable once accepted; supersede by a new ADR, never edit in place)
- [.claude/](/.claude/) — Claude Code configuration (commands, plans)

---

## 1. Python rules (backend)

**Every function, method, and class MUST have:**
1. Full type hints on every parameter, return value, and class attribute. No bare `Any` unless justified in a docstring.
2. A Google-style docstring. Module-level docstrings too.
3. Pydantic `BaseModel` for **all** structured data crossing a boundary (API request/response, LLM I/O, DB rows, config). No raw dicts for structured payloads.

**Google docstring format (use verbatim shape):**

```python
def score_email(email: EmailMessage, rubric: ScoringRubric) -> PriorityScore:
    """Score an email against the user's priority rubric.

    Args:
        email: Parsed Gmail message with headers and body.
        rubric: User-defined scoring weights and keywords.

    Returns:
        Priority score in range [0, 100] with per-criterion breakdown.

    Raises:
        ScoringError: If the rubric references an unknown field.
    """
```

**Formatting & linting — enforced by [pyproject.toml](pyproject.toml):**
- `ruff format` (Black-compatible, 100-char line length)
- `ruff check` with `D` (pydocstyle, google convention), `ANN` (type annotations), `I` (isort), `B`, `UP`, `N`, `PL`
- `mypy --strict`

**Pydantic conventions:**
- Subclass `BaseModel`; use `Field(..., description="...")` for every field.
- Prefer `model_config = ConfigDict(frozen=True)` for value objects.
- Use `pydantic-settings` for env config, never `os.getenv` directly in business logic.

When you generate Python code, these rules are non-negotiable — produce code that passes `ruff check`, `ruff format --check`, and `mypy --strict` on the first run.

---

## 2. React / TypeScript rules (frontend)

**Every component, hook, and exported function MUST have:**
1. TypeScript types on every prop, return value, and state hook. No implicit `any`.
2. A JSDoc block in Google style describing purpose, `@param`, `@returns`, `@throws` where applicable.
3. Named exports (no default exports except for route-level pages).

**JSDoc format:**

```ts
/**
 * Renders the priority inbox list for a single day.
 *
 * @param props - Component props.
 * @param props.date - Day to display, in ISO format.
 * @param props.emails - Pre-scored emails sorted by priority desc.
 * @returns The list element, or a skeleton if emails are empty.
 */
export function PriorityList(props: PriorityListProps): JSX.Element { ... }
```

**Formatting & linting — enforced by [frontend/eslint.config.js](frontend/eslint.config.js) and [frontend/.prettierrc](frontend/.prettierrc):**
- Prettier (100-char, single quotes, trailing commas)
- ESLint: `eslint-config-google`, `@typescript-eslint/recommended`, `react`, `react-hooks`, `jsdoc` plugin with `google` tag style
- `jsdoc/require-jsdoc` enforced on exported functions, components, and hooks

When you generate TS/TSX code, these rules are non-negotiable — produce code that passes `npm run lint` and `npm run format:check` on the first run.

---

## 3. Planning rule

All plan documents live in [.claude/plans/](.claude/plans/). Name files `YYYY-MM-DD-<slug>.md`. Never place plans at repo root or inside `backend/` or `frontend/`.

---

## 4. Git rules — ask first, always

**Do NOT push to any remote without explicit user permission.** Committing locally is fine when the user says "commit"; pushing is a separate, explicit authorization.

**Do NOT push, merge, force-push, or rebase onto `main` without explicit user permission.** Even if the user says "push" in general, confirm again if the target is `main`. Feature branches are the default workflow.

**Do NOT:**
- Run `git push` unless the user explicitly said "push" in this conversation.
- Run `git push origin main` ever without a fresh, explicit confirmation naming `main`.
- Force-push (`--force`, `--force-with-lease`) unless the user explicitly requested it.
- Bypass hooks (`--no-verify`).

**Do:**
- Create commits locally when asked.
- Work on feature branches by default.
- Open PRs rather than merging directly.

---

## 5. README auto-update rule

Whenever a change alters **user-visible project state**, update [README.md](README.md) in the same change. Triggers:
- New or removed top-level dependency (package.json, pyproject.toml)
- New env var required to run the app
- New setup / install / run step
- New top-level directory or entry point
- New slash command or developer command
- Stack change (new service, new database, swapped framework)

Do NOT update the README for internal refactors, test additions, or doc-only edits elsewhere. The README is the "getting started & what's in the box" doc — keep it current, keep it minimal.

---

## 6. Slash commands

- [/make-docs](.claude/commands/make-docs.md) — generate Swagger/OpenAPI spec at version `1.0.0`.
- [/test](.claude/commands/test.md) — run Python + React test suites.

---

## 8. Commands

The [Makefile](Makefile) is the single source of truth — CI calls the same targets. Full list is in [README.md](README.md). A few invocations that are easy to get wrong:

- **Run a single Python test:** `pytest backend/tests/unit/test_config.py::test_name -q`. `make test` adds `-m "not e2e and not eval"` — reuse that filter when running pytest directly (the `e2e` and `eval` markers are opt-in, guarded by `PLAYWRIGHT=1` / `EVAL=1`). Markers are declared in [pyproject.toml](pyproject.toml): `unit`, `integration`, `e2e`, `eval`.
- **Run pytest with asyncio:** `asyncio_mode = "auto"` is set — do not add `@pytest.mark.asyncio`; just define `async def test_*`.
- **Coverage:** `make coverage` fails under 80% (`COVERAGE_FLOOR`). Five modules are pinned at 100% per plan §20.1 — `LLMClient` ([backend/app/llm/client.py](backend/app/llm/client.py)) is one; do not regress their coverage.
- **Frontend:** Lint/test targets silently skip until `frontend/package-lock.json` exists (`FRONTEND_READY` gate in the Makefile). When adding frontend code, run `make bootstrap` first to materialize the lockfile.
- **OpenAPI regen:** Always via `make docs` or [/make-docs](.claude/commands/make-docs.md) — it pins `info.version` to `1.0.0` and regenerates `frontend/src/api/schema.d.ts`. Never hand-edit [packages/contracts/openapi.json](packages/contracts/openapi.json).
- **Alembic revision:** `make migrate-rev MSG="add foo table"`. Always run `make migrate` locally before committing a new revision to confirm it upgrades + downgrades cleanly.
- **Local services:** `docker compose up -d` brings up Postgres (5432) and LocalStack (4566, serves SQS/SSM/S3/KMS/events/scheduler). `make bootstrap` does this for you.

---

## 9. Big-picture architecture

### Two runtime shapes, one codebase
The backend image ships three entrypoints selected by `BRIEFED_RUNTIME` (see [backend/app/core/config.py](backend/app/core/config.py)):

- `local` — uvicorn serves [backend/app/main.py](backend/app/main.py) (`app.main:app`). Used in dev + tests.
- `lambda-api` — [backend/app/lambda_api.py](backend/app/lambda_api.py) wraps the FastAPI app with Mangum behind a Lambda Function URL + CloudFront (ADR 0003).
- `lambda-worker` / `lambda-fanout` — [backend/app/lambda_worker.py](backend/app/lambda_worker.py) exposes `sqs_dispatcher` (routes by source queue ARN to handlers in [backend/app/workers/handlers/](backend/app/workers/handlers/)) and `fanout_handler`.

**SnapStart-friendly init matters.** Settings hydration (SSM) and `structlog.configure` run at module import, not inside a factory, so SnapStart snapshots a fully-initialized process. Keep module-level imports minimal in lambda_api/lambda_worker; defer heavy imports (boto3, httpx, `google.generativeai`) to the handler body — the existing per-file `ruff` ignores (`PLC0415`) document where this is intentional.

### The daily pipeline (SQS fan-out)
EventBridge Scheduler → `fanout_handler` → enumerates `connected_accounts` → enqueues one `IngestMessage` per account → downstream workers fan out per stage. Each stage has its own SQS queue and its own handler; discriminated-union payloads live in [backend/app/workers/messages.py](backend/app/workers/messages.py):

```
fanout → ingest → classify ─┬─▶ summarize (per-email + newsletter clusters)
                            └─▶ jobs (extract + corroborate + predicates)
```

Queue URLs are injected via env (`BRIEFED_*_QUEUE_URL`). The ingest handler opportunistically chains into `classify` when `BRIEFED_CLASSIFY_QUEUE_URL` is set — other stages follow the same pattern. **Never invent new message shapes inline**; add a class to `workers/messages.py` with `ConfigDict(frozen=True, extra="forbid")` and a `kind` literal.

### LLM abstraction — one client, many providers
Every LLM call goes through [backend/app/llm/client.py](backend/app/llm/client.py) `LLMClient`, which owns:

- **Fallback chain** — `settings.llm.fallback_chain` (Gemini Flash primary, Claude Haiku 4.5 fallback per ADR 0002).
- **Retries** — 3 attempts, exponential backoff + jitter, only on `retryable=True` errors.
- **Circuit breaker** — trips after 5 consecutive failures; fallback kicks in while open.
- **Cost + token logging** — one `PromptCallLog` row per call.
- **Hard caps** — e.g. Claude Haiku 4.5 at 100 calls/day (plan §19.15).

Providers implement [backend/app/llm/providers/base.py](backend/app/llm/providers/base.py); add new providers there, never bypass `LLMClient`. Prompts live in [packages/prompts/](packages/prompts/) as versioned bundles with JSON Schemas — reference them by `(name, version)`, never inline a prompt string in business logic.

### Data model + encryption
- SQLAlchemy 2.0 async models in [backend/app/db/models.py](backend/app/db/models.py); sessions via [backend/app/db/session.py](backend/app/db/session.py) (asyncpg over the Supabase pooler in prod per ADR 0004).
- Alembic migrations under [backend/alembic/versions/](backend/alembic/versions/).
- **Two KMS CMKs** (ADR 0008): `alias/briefed-*-token-wrap` envelopes OAuth tokens; `alias/briefed-*-content-encrypt` envelopes email bodies. Helpers live in [backend/app/core/security.py](backend/app/core/security.py) and [backend/app/core/content_crypto.py](backend/app/core/content_crypto.py) — always go through these; they bind `user_id` into the encryption context.

### Mailbox abstraction
ADR 0007 defines `MailboxProvider` in [backend/app/domain/providers.py](backend/app/domain/providers.py). Gmail is the only concrete implementation today ([backend/app/services/gmail/](backend/app/services/gmail/)). If you add IMAP/Outlook, implement the interface — do not special-case Gmail further in pipelines.

### Config & secrets
`pydantic-settings` `Settings` in [backend/app/core/config.py](backend/app/core/config.py), accessed via `get_settings()` (memoized). In Lambda runtimes it pulls secrets from SSM at cold-start via `_SSM_FIELD_MAP`; missing required secrets fail init hard. Locally it reads `.env` (template at [.env.example](.env.example)). **Never call `os.getenv` in business logic** — route through `Settings` so tests + SSM hydration keep working.

### Release policy
Release 1.0.0 is **recommend-only** (ADR 0006): the agent never clicks unsubscribe / archives / sends on the user's behalf. If you add a destructive action path, it must be gated behind an explicit user confirmation flow and documented in a new ADR.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
