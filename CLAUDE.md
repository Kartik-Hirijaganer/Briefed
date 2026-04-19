# Briefed — Project Rules

Personal AI email agent. Stack: Python · FastAPI · Claude API · Gmail API · Supabase · React · PWA.

Monorepo layout:
- [backend/](backend/) — FastAPI + Pydantic + Claude API pipeline (Python 3.11+)
- [frontend/](frontend/) — React PWA dashboard
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
