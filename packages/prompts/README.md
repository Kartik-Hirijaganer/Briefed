# packages/prompts

Versioned LLM prompt bundles. Every prompt shipped in Briefed lives here —
**never inline in application code** — so the backend `PromptRegistry`
(`backend/app/services/prompts/registry.py`, lands in Phase 2) can load a
specific version by ID and the Promptfoo eval suite can diff changes.

## Layout

```
prompts/
├── triage/
│   └── v1.md                  # classification prompt
├── summarize/
│   ├── relevant/v1.md         # per-email must-read / good-to-read summaries
│   └── tech_news/v1.md        # clustered newsletter / tech-news digest
├── jobs/
│   └── v1.md                  # JobMatch extraction
└── schemas/
    ├── triage.v1.json         # JSON Schema for TriageDecision tool-use
    ├── summary.v1.json
    └── job_match.v1.json
```

Phase 0 ships the directory skeleton only. Prompt bodies land with their
owning phase (Phase 2 triage, Phase 3 summarize, Phase 4 jobs).

## Versioning rules

- Prompts are append-only. `v1.md` is frozen once Promptfoo baselines are
  committed; improvements land as `v2.md` with a new registry entry.
- Schema files are JSON Schema Draft 2020-12; tool-use payloads must set
  `extra="forbid"` on the Pydantic side so silent schema drift is impossible.
- Every prompt file begins with a YAML frontmatter block declaring `id`,
  `version`, `owner`, `provider` (`gemini` / `anthropic`), and the
  `output_schema` pointer. Loader validates the frontmatter on boot.

## Why this is its own package

Keeps prompts diffable without Python churn; lets the frontend ship the same
prompt catalog to an admin UI if/when that ships.
