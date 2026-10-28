# packages/prompts

LLM prompt bundles. Every prompt shipped in Briefed lives here — **never
inline in application code** — so the backend `PromptRegistry`
(`backend/app/services/prompts/registry.py`) can load it by `(id, version)`
and the Promptfoo eval suite can diff changes.

## Layout

```
prompts/
├── category_digest/
│   └── v1.md                  # run-scoped per-category digest rollups
├── newsletter_group/
│   └── v1.md                  # clustered newsletter / tech-news digest
├── triage/
│   └── v2.md                  # 3-label daily triage prompt
├── summarize/
│   └── v1.md                  # per-email must-read / good-to-read summaries
├── unsubscribe_borderline/
│   └── v1.md                  # LLM tie-break for borderline unsubscribe senders
└── schemas/
    ├── category_digest.v1.json
    ├── newsletter_group.v1.json
    ├── summarize_relevant.v1.json
    ├── triage.v1.json
    ├── triage.v2.json         # JSON Schema for current TriageDecision
    └── unsubscribe_borderline.v1.json
```

## File format

- Every prompt file begins with a YAML frontmatter block declaring `id`,
  `version`, `owner`, `model` (a key from `packages/config/llm/catalog.yml`),
  and the `output_schema` pointer. Loader validates the frontmatter on boot.
- The body is the **system message** (instructions, output schema, input
  description, examples), then a line reading exactly `<!-- user message -->`,
  then the **user-message template**. Only the user template may contain
  `{{placeholders}}`, so email content never lands in the system message.
- Schema files are JSON Schema Draft 2020-12; tool-use payloads must set
  `extra="forbid"` on the Pydantic side so silent schema drift is impossible.

## Editing rules

- Edit prompt files in place; there is no need to add a `v2.md` for a change.
  On the next worker run, `PromptRegistry.sync_to_db` refreshes the existing
  `prompt_versions` row (same `id` and `version`) with the new text and hash.
- Size `max_tokens` above the largest output the prompt asks for, with
  headroom. A response cut off at the cap is invalid JSON and is discarded.

## Why this is its own package

Keeps prompts diffable without Python churn; lets the frontend ship the same
prompt catalog to an admin UI if/when that ships.
