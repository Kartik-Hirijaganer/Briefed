# packages/prompts

Versioned LLM prompt bundles. Every prompt shipped in Briefed lives here —
**never inline in application code** — so the backend `PromptRegistry`
(`backend/app/services/prompts/registry.py`, lands in Phase 2) can load a
specific version by ID and the Promptfoo eval suite can diff changes.

## Layout

```
prompts/
├── category_digest/
│   └── v1.md                  # run-scoped per-category digest rollups
├── newsletter_group/
│   └── v1.md                  # clustered newsletter / tech-news digest
├── triage/
│   ├── v1.md                  # original 5-label classification prompt
│   └── v2.md                  # 3-label daily triage prompt
├── summarize/
│   └── v1.md                  # per-email must-read / good-to-read summaries
└── schemas/
    ├── category_digest.v1.json
    ├── newsletter_group.v1.json
    ├── summarize_relevant.v1.json
    ├── triage.v1.json
    ├── triage.v2.json         # JSON Schema for current TriageDecision
    └── unsubscribe_borderline.v1.json
```

Phase 0 ships the directory skeleton only. Prompt bodies land with their
owning phase (Phase 2 triage, Phase 3 summarize, Phase 4 category digests).

## Versioning rules

- Prompts are append-only. `v1.md` is frozen once Promptfoo baselines are
  committed; improvements land as `v2.md` with a new registry entry.
- Schema files are JSON Schema Draft 2020-12; tool-use payloads must set
  `extra="forbid"` on the Pydantic side so silent schema drift is impossible.
- Every prompt file begins with a YAML frontmatter block declaring `id`,
  `version`, `owner`, `model` (a key from `packages/config/llm/catalog.yml`),
  and the `output_schema` pointer. Loader validates the frontmatter on boot.

## Why this is its own package

Keeps prompts diffable without Python churn; lets the frontend ship the same
prompt catalog to an admin UI if/when that ships.
