# Briefed — Daily Triage Revamp Plan

> Canonical plan, maintained in **both** `.claude/plans/` and `.Codex/plans/` (this repo is governed by
> both CLAUDE.md → Claude Code and AGENTS.md → Codex, which point at their respective dirs). Keep the two
> copies identical. Implementation branch: `feat/daily-triage-revamp`.

---

## 1. Context — why this change

Briefed is structurally a mature app: OpenRouter routing (Gemini 2.0 Flash primary + Claude Haiku 4.5
fallback) with retries/circuit-breaker/USD-cap, multi-account Gmail ingestion, a 12-module Terraform
stack, GitHub Actions CI/CD, Supabase Postgres, and a working React PWA. **The resume bullet is already
largely true.** The problems:

1. **The daily output isn't useful** (your own answer). Per-email and newsletter-cluster summaries exist,
   but there's **no synthesized per-category rollup** — no "here's your Must-Read today" read in 30 seconds.
2. **Sprawl past the focused vision** — 5 categories, job extraction, unsubscribe ranking, newsletter
   clustering, Presidio PII redaction.
3. **You can't act on the brief** — no way to clear mail you've reviewed.
4. **Run boundaries are untrustworthy** — `fanout.py` creates no `digest_runs` row (scheduled runs are
   invisible), and pending-work checks are **account-scoped, not run-scoped** ([runs.py:229](backend/app/services/runs.py),
   [runs.py:335](backend/app/services/runs.py)), so a crashed prior run can wedge a new one. **Trustworthy
   run boundaries are a prerequisite for correct per-category digests**, so reliability is sequenced first.

**Intended outcome:** a focused, reliable, genuinely-useful daily brief in a single PWA dashboard — 3
categories, real per-category summaries, mark-read in Gmail, all product knobs in **YAML config**, models
swappable from **one `catalog.yml`**, built by **extending** existing tables/endpoints and **cutting** the
non-core.

### Decisions locked in

| Decision | Choice |
|---|---|
| Primary blocker | Digest isn't useful → headline = per-category summaries |
| Delivery | PWA only (no email/push) |
| Keep ON | Core triage, newsletter clustering, unsubscribe suggestions |
| Cut | Job extraction (removed), Presidio PII redaction (removed; light scrubber stays) |
| Categories | 3: Must-Read / Good-to-Read / Ignore (`waste`→Ignore; `needs_review`→internal flag) |
| Mark-as-read | Real Gmail mark-read via `gmail.modify`, code-restricted to UNREAD removal, new ADR, re-consent |
| Scan scope | **Unread-only** (matches "classify unread emails"; makes marked-read mail not reappear) |
| LLM config | `catalog.yml` is the single source for models; `LLMClient` is the call library; prompts use catalog *keys* |
| UI | One Dashboard: KPI cards filter a paginated, category-tagged email table |
| Reliability infra | KMS, fallback, retries, breaker, DLQ, idempotency — all stay |

---

## 2. Executive summary — what the product is, in plain terms

**Briefed is your personal inbox bouncer.** Each morning it reads the *unread* mail across your 3 Gmail
accounts, decides what deserves attention, and hands you a one-screen brief:

- **Must-Read** — needs *you* today (a real person asked something, a security alert, a meeting change).
  Briefed writes a short paragraph: *"3 things need you: X replied about…, your card expires…, standup moved…"*
- **Good-to-Read** — skim later (newsletters you read, service updates). Same-topic newsletters group into one summary.
- **Ignore** — receipts, promos, noise. Counted, not summarized.

You open the PWA, read two short summaries, then work a single table below — filter it by tapping a
category KPI card, and **mark mail read** (one row, or "select all" on Ignore), which clears it straight
out of your real Gmail so it never comes back. Simple **rules** ("from my manager → Must-Read", "subject
has `invoice` → Ignore") run *before* the AI, so common mail is instant and free. It runs on AWS at
**near-zero cost**. Swapping a model later is a **one-line edit to `catalog.yml`**.

---

## 3. What stays, what changes, what's cut

```
KEEP (and it's the resume story)              CHANGE / ADD (the revamp)
────────────────────────────────             ──────────────────────────────────────────
✓ OpenRouter: Gemini 2.0 Flash + Haiku        ⟳ 5 categories → 3
✓ Multi-account (3) Gmail ingest              ★ NEW per-category digest summaries (extend `summaries`)
✓ User rules (RubricRule) + a real UI         ★ NEW mark-as-read in Gmail (gmail.modify, new ADR)
✓ Newsletter clustering, Unsubscribe          ★ NEW run-membership + visible scheduled runs
✓ Terraform IaC, GitHub Actions CI/CD         ⟳ Models → catalog.yml; prompts use catalog keys
✓ KMS, retries, breaker, DLQ, idempotency     ⟳ One Dashboard: KPI filters + paginated tagged table
✓ Supabase Postgres, SnapStart                ⟳ Unread-only scan; ~12 constants → YAML config

                                              CUT (less is more)
                                              ✂ Job extraction (tables/prompt/API/UI/worker)
                                              ✂ Presidio PII redaction (keep light identity scrubber)
```

---

## 4. Architecture diagrams

### 4.1 The daily loop (plain English)

```
  Scheduled each morning (your timezone, your time)  ── or tap "Scan now"
        │
        ▼
  Read UNREAD mail across your 3 Gmail inboxes   (read mail is skipped — won't reappear)
        │
        ▼
  Sort each email →  YOUR RULES first (instant, free)  →  AI only if rules miss
        │
        ├───────────────┬──────────────────┬───────────────┐
        ▼               ▼                  ▼
   ┌──────────┐  ┌──────────────┐   ┌──────────┐
   │MUST-READ │  │ GOOD-TO-READ │   │  IGNORE  │
   └────┬─────┘  └──────┬───────┘   └────┬─────┘
        ▼               ▼                ▼ (newsletters grouped by topic)
   ┌─────────────────────────────────┐   "Mark all read" ──▶ clears UNREAD in Gmail
   │ Write ONE short brief per pile   │ ◀── the headline feature (built once the run drains)
   └────────────────┬─────────────────┘
                    ▼
        Open Briefed PWA → read brief → filter table by KPI → mark read → done
```

### 4.2 System architecture on AWS

```
┌──────────────────────────── AWS (Terraform IaC) ────────────────────────────┐
│  EventBridge      ┌────────┐   SQS (ingest→classify→summarize)  ┌─────────┐  │
│  Scheduler ─────▶ │ fanout │ ──── creates digest_runs row ─────▶ │ worker  │  │
│  (your schedule)  │ Lambda │      + run membership (NEW)         │ Lambdas │  │
│                   └────────┘                                     └────┬────┘  │
│  CloudFront         ┌──────────────────┐   read  ◀───────────────────┘       │
│  (PWA + API) ─────▶ │   api Lambda     │ ───── mark-read (gmail.modify) ──▶ Gmail
│   IAM-signed        │ FastAPI + Mangum │      (NEW write edge, UNREAD only)  │
│                     └────────┬─────────┘   OpenRouter ─▶ Gemini 2.0 Flash    │
│  KMS (2 CMKs)   SSM secrets  │             (single LLM   ↳ Claude Haiku 4.5  │
└──────────────────────────────┼──────── gateway via catalog.yml ─────────────┘
                               ▼
                     Supabase PostgreSQL
```

### 4.3 LLM "AI library" — change a model in one place

```
packages/config/llm/catalog.yml        ◀── EDIT HERE ONLY to swap a model/version
  models: { gemini-flash: {openrouter_id: google/gemini-2.0-flash-001, ...},
            claude-haiku: {openrouter_id: anthropic/claude-haiku-4.5, daily_call_cap: 100, ...} }
  primary: gemini-flash   fallbacks: [claude-haiku]
        │ loaded + validated (frozen Pydantic ModelCatalog; fails hard if malformed)
        ▼
backend/app/llm/catalog.py  resolve(key)·chain()  →  client.py LLMClient (fallback/retries/breaker/cost)
        ▲ prompts/*/v*.md frontmatter `model: gemini-flash` (keys, validated against the catalog at boot)
```

### 4.4 Data + API extension (extend, never duplicate)

```
summaries table — 3rd "kind" (no new table)            GET /api/v1/digest/today (extended response)
  kind='category_digest' → run_id+category  ◀NEW         + category_summaries:[{category,narrative_md,groups}] ◀NEW
digest_run_emails — NEW join table (run_id, email_id)  → run-scoped finalization (not account-scoped)
GET /api/v1/emails — + q/sender/date/has_summary/offset; row carries `bucket` as a category tag  ◀NEW
POST /api/v1/emails/mark-read {email_ids[] | category, account_id?}   ◀NEW (the only new endpoint)
```

---

## 5. Design principles (your constraints, made concrete)

1. **No hardcoded values → YAML config.** Frozen, memoized loaders for `app_config.yml` (product knobs)
   and `llm/catalog.yml` (models). Secrets stay in `Settings`/SSM. **In Lambda, missing/malformed config
   fails hard** (local/test may fall back to defaults) — a silent fallback in prod would defeat the goal.
2. **Models swappable from one file.** `catalog.yml` is the single source; prompts use catalog *keys*
   (validated against the catalog at boot); `LLMClient` is the unchanged call library.
3. **Extend, don't duplicate — APIs.** Per-category summaries ride `GET /digest/today`; daily-use filters
   and pagination extend `GET /emails`; `POST /runs` gains a `mode`. The **only** new endpoint is
   `POST /emails/mark-read` (one action endpoint covers per-email and bulk).
4. **Extend, don't duplicate — tables.** Category summaries reuse `summaries` (+2 nullable cols); rules
   reuse `rubric_rules` (+`name`); mark-read reuses `emails.labels`. The one genuinely new table is
   `digest_run_emails` (run membership) — needed for correct, run-scoped completion.
5. **Less is more.** Jobs + Presidio removed (not dead-gated). A `features` block remains as the documented
   re-add seam for the optional features that stay.
6. **Reliability before the headline.** Run identity/membership and run-scoped finalization land *before*
   category digests, so digests are built from complete, trustworthy run boundaries — never partial.

---

## 6. Adopted design decisions

Proposed earlier as options; all **accepted** and folded into the phases below.

| # | Decision | Lands in |
|---|---|---|
| D1 | Keep 3 user-facing labels **Must-Read / Good-to-Read / Ignore** (no rename) | Phase 1 taxonomy |
| D2 | Low-confidence surfaces as a row **badge** ("🤔 double-check") from the `needs_review` flag — **not** a 4th bucket | flag set Phase 1 (exposed on `EmailRowOut`); badge rendered Phase 6 |
| D3 | **No new categories now** (a 4th "Respond vs FYI" split is deferred) | §11 Out of scope |
| D4 | **Default seed rules** so Briefed is useful day 1 (`packages/config/seeds/rubric_rules.yml`) | Phase 1 rules |
| D5 | **Resume wording:** "Claude Haiku **via OpenRouter**," not "Anthropic API"; keep the single OpenRouter gateway (no direct Anthropic provider, per ADR 0009) | resume bullet; LLM design Phase 0 |
| D6 | **Defer** learning rules from your mark-read / override behavior | §11 Out of scope |
| D7 | Dashboard shows a "**N sorted by your rules (free)**" stat (count of `decision_source='rule'`) | count on `digest/today` Phase 4; rendered Phase 6 |

---

## 6.1 Screens — information architecture

**One working Dashboard.** Category **KPI cards act as filters** over one **paginated, category-tagged email table**.

| Screen | Route | Purpose |
|---|---|---|
| **Dashboard** | `/` | narrative summaries + **KPI cards (All · Must-Read · Good-to-Read · Ignore) that filter** a **paginated, category-tagged email table** w/ per-row + bulk mark-read; Scan-now; freshness; cost |
| Unsubscribe | `/unsubscribe` | Noisy-sender hygiene (quiet link from Dashboard) |
| History | `/history` + `/history/:runId` | Run history + detail (confirm scheduled runs ran) |
| **Settings** | `/settings` | Tabs: **Accounts · Schedule · Rules · Preferences** |
| Login · OAuth callback · Not Found | `/login` · `/oauth/callback` · `/*` | Auth + 404 |

**Dashboard zones:** (1) header — freshness, Scan-now, cost; (2) **narrative summaries** (30-sec brief;
newsletters fold into the Good-to-Read summary); (3) **KPI cards** — counts that double as table filters
("All" clears; low-confidence shows as a row badge per D2); (4) **email table** — paginated, each row a
**category tag** + sender/subject/received/summary + mark-read, with **bulk select-all** (great for Ignore).

**Cut / merged:** ✂ `/waste` (→ Ignore) · ✂ `/jobs` · ⟳ `/news` → Good-to-Read summary · ⟳ `/settings/prompts`
→ Rules · ⟳ `/must-read|good-to-read|ignore` → the one Dashboard table (KPI filter). Net: **~6 top-level
screens + 4 Settings tabs** (from 15). Unsubscribe stays its own screen unless you'd rather fold it in too.

---

## 7. Phased implementation plan

> Each phase is independently shippable and leaves the system consistent. **Order:** config → taxonomy/API/rules
> → cut sprawl → **reliability & run identity** → **headline digests** (on trustworthy boundaries) →
> mark-read backend → PWA (consumes the finished backend). Reliability precedes digests; the mark-read
> endpoint precedes its UI.

### Phase 0 — Config (YAML) + `catalog.yml` AI-library  *(behavior-neutral)*

**Goal:** externalize product knobs + model defs to YAML. No behavior change (jobs is untouched here — it's
removed wholesale in Phase 2, so no half-gated state).

**Build:**
- Add `pyyaml` + `types-PyYAML` ([pyproject.toml](pyproject.toml)); a small `yaml.safe_load` helper.
- **`packages/config/app_config.yml`** + frozen memoized `get_app_config()` ([core/app_config.py](backend/app/core/app_config.py)),
  mirroring `get_settings()`. Blocks: `features`, `classification`, `api`, `taxonomy`, `scan`. **In Lambda
  runtime, missing/malformed config raises at init** (like Settings/SSM); local/test falls back to model defaults.
- `features` flags as declarative config: `jobs`, `unsubscribe`, `newsletter_clustering`, `presidio`
  (the kept optional features read these; `jobs` stays as the documented re-add seam — Phase 0 does not
  change jobs behavior).
- `scan`: `lookback_days` (replaces hardcoded `newer_than:{bootstrap_lookback_days}d` in
  [gmail/provider.py:95](backend/app/services/gmail/provider.py) — neutral) + `unread_only` (default
  **false**; Phase 5 flips it).
- **`packages/config/llm/catalog.yml`** + refactor [catalog.py](backend/app/llm/catalog.py) to load it into
  a frozen Pydantic `ModelCatalog` (validators: `primary`/`fallbacks` ∈ `models`). **Keep `resolve()`/`chain()`/
  `CATALOG`/`PRIMARY`/`FALLBACKS` API stable** ([client.py](backend/app/llm/client.py) is 100%-pinned; `factory.py`
  unchanged). **Malformed/missing catalog fails hard** (a wrong model route must never be silent).
- **Prompts reference catalog keys:** frontmatter `model: gemini-flash` (fix stale `gemini-1.5-flash`).
  **Validate every `PromptSpec.model` against `ModelCatalog` keys at registry load/boot**; update
  `PromptRegistry` docs + tests.
- Migrate confirmed constants → `app_config.yml` (defaults == today): `0.55` thresholds
  ([pipeline.py](backend/app/services/classification/pipeline.py)); `_PREVIEW_LIMIT` + pagination defaults
  ([frontend.py:66](backend/app/api/v1/frontend.py), [emails.py:77](backend/app/api/v1/emails.py));
  `_RECOMMENDATION_CONFIDENCE_MIN`, `_TOP_DOMAIN_CAP` ([unsubscribes.py](backend/app/api/v1/unsubscribes.py));
  `_SUMMARIZABLE_LABELS`, bucket sets → `taxonomy`. `daily_call_cap` → `catalog.yml`. Secrets stay in `Settings`.

**Test cases:** `app_config` defaults == YAML; frozen + extra-forbid; **Lambda runtime + missing config →
raises; local + missing → defaults**; memoized. `catalog` loads from YAML; `resolve`/`chain` stable; missing
primary / unknown fallback / **malformed file** raise. Registry: unknown `PromptSpec.model` key → boot error.
Full suite green at defaults (proves neutrality).

---

### Phase 1 — Taxonomy 5→3 + emails API + rules + prompt v2  *(behavior-changing)*

**Goal:** 3 categories; daily-use list filters + pagination; production-grade rules; eval-gated prompt.

**Build:**
- **Prompt v2 (append-only):** `packages/prompts/triage/v2.md` + `schemas/triage.v2.json` — 3 categories,
  `is_newsletter` only (**drop `is_job_candidate`**), folded `waste` guidance into `ignore`, **injection-resistant**
  (email text is untrusted). Classify uses `triage` v2.
- **Pydantic/pipeline:** `TriageCategory` → 3 ([llm/schemas.py](backend/app/llm/schemas.py)); pipeline keeps
  the 3-way label and sets a boolean `Classification.needs_review` for low-confidence (the D2 source);
  all-providers-fail → `label='ignore', needs_review=True`.
- **Rules (extend `rubric_rules`):** add `name`; add a `subject_contains`/topic-keyword predicate
  ([rubric.py](backend/app/services/classification/rubric.py)); `_normalize_action_label` maps legacy
  `'waste'`→`'ignore'`; known-waste-sender → `ignore`; seed `packages/config/seeds/rubric_rules.yml` (D4);
  **user overrides protected** from reclassification.
- **Richer `GET /emails` (extend, no new endpoint):** add `q` (subject/sender), `sender`, `received_after`,
  `received_before`, `has_summary`, **`offset`** (pagination; `total` already returned → page count); keep
  `bucket`/`account_id`/`limit`. `EmailRowOut` exposes `bucket` (rendered as a **category tag**) and the
  `needs_review` flag (for the **D2** badge); KPI cards drive `?bucket=` (none = "All"). Narrow `EmailBucket`
  literal to 3 (auto-422 on `?bucket=waste`).
- **Migration `0010`:** add `classifications.needs_review`; remap labels (`waste→ignore`,
  `needs_review→ignore`+flag, `newsletter→good_to_read`, `job_candidate→good_to_read`); **set
  `is_job_candidate=false` for all rows** (deprecation cleanup — drains the jobs backlog so it can't dangle
  before Phase 2 removes it); swap `ck_classifications_label` → 3-value via `op.batch_alter_table`; add
  `rubric_rules.name`. Reversible. Sync ORM.
- Remove `DigestCounts.waste`; counts built from `taxonomy.user_facing_buckets`. `make docs`.
- **Quality gate:** `make eval` golden set across personal/work/newsletter/promo/receipt/security/calendar/
  recruiter/spam — category accuracy, valid JSON, injection refusal, no PII in rationale.

**Test cases:** triage v2 enum == literal; `waste`/`needs_review` raise; low-conf sets flag not label; rubric
topic/predicate/regex/unknown-key; override protected; `GET /emails` filters + `offset` + 422 on `waste`;
`DigestCounts` has no `waste`. **Gates:** `make migrate` 0010 up+down; `make eval` thresholds.

---

### Phase 2 — Simplify: remove jobs + Presidio  *(behavior-changing)*

**Goal:** delete the sprawl so the finalization rework (Phase 3) lands on a clean base.

**Build — jobs (migration `0011`):** delete worker `handlers/jobs.py` + dispatcher arm; **the enqueue at
[lambda_worker.py:300](backend/app/lambda_worker.py) (`enqueue_unextracted_for_account`) and the classify-stage
job enqueue**; `services/jobs/`; `api/v1/jobs.py`+`job_filters.py`; `schemas/jobs.py`; `JobMatch`/`JobFilter`
models; `JobExtractMessage`; prompt `jobs/v1.*`. **Finalization:** remove `_pending_jobs`, the field/term,
`JobMatch` import, `_JOB_LABEL`; drop `"job_extract"` from `_NON_FATAL_PROMPT_NAMES`. Migration mirrors `0004`
(drop `job_filters`/`job_matches`, drop `classifications.is_job_candidate`); reversible. Drop `is_job_candidate`
from rubric/pipeline writes + the unsubscribe positive-label set.

**Build — Presidio:** `build_default_chain` reads `features.presidio` (default false); keep the zero-dep
identity scrubber + regex sanitizer. Delete `llm/redaction/presidio.py`; remove `presidio-*` + the `numpy<2.0`
pin ([pyproject.toml](pyproject.toml)); `build_default_chain(presidio_enabled=True)` raises ("removed, not
hidden"). **New superseding ADR** (redaction is governed by immutable ADR 0010). **README** update.

**Test cases:** delete jobs test files; edit run/pipeline/frontend/worker tests to drop job fixtures.
`integration`: full pipeline with no jobs queue env → `complete`. `unit`: `RunProgressSnapshot` has no
`pending_jobs`; chain = `[identity?, regex]`; `presidio_enabled=True` raises; identity scrubber still masks.
**Gates:** `make migrate` 0011 up+down; `make coverage` ≥80% (client.py still 100%); `make docs` (`/jobs` gone).

---

### Phase 3 — Reliability & run identity  *(prerequisite for trustworthy digests)*

**Goal:** every scheduled run is visible; completion is **run-scoped**, not account-scoped.

**Build:**
- **Fanout creates `digest_runs`:** [fanout.py](backend/app/workers/handlers/fanout.py) creates + commits a
  `scheduled` DigestRun per due user before enqueueing, carrying its id as `run_id` — scheduled scans now
  appear in `/history` and `/runs/{id}` like manual ones.
- **Run-membership table `digest_run_emails`** (`run_id`, `email_id`, PK both) — **migration `0012`**.
  Stamped at ingest for the run's emails, and by `reclassify_recent` for the emails it targets. This is the
  explicit run boundary (more robust than `created_at >= run.started_at`, and it's what makes
  `reclassify_recent` over *existing* mail correct).
- **Run-scoped finalization:** `_pending_unclassified` / `_pending_summaries` (and clusters) join
  `digest_run_emails` for the run instead of scanning all account emails ([runs.py:229](backend/app/services/runs.py),
  [runs.py:335](backend/app/services/runs.py)). A crashed prior run's leftovers can't wedge a new run;
  zero-new-email runs finalize cleanly.
- **`POST /runs` modes (extend `ManualRunRequest`):** `mode: incremental | reclassify_recent`, `window_days`,
  `include_user_overrides=false` — re-triage recent mail after editing rules without clobbering overrides;
  stamps membership for the targeted set.
- **Alarms** (existing `alarms` module + Terraform): failed-run, stale-lock, SQS DLQ depth, scheduler health,
  daily cost-cap. Wire PWA `FreshnessBadge` to `last_successful_run_at`.

**Test cases:** `unit` `run_fanout` creates a committed DigestRun; membership-scoped pending ignores
non-member (pre-run) emails; zero-new run → `complete`; stale-lock clears; `reclassify_recent` stamps
membership + skips overrides; alarm/stale predicate. `integration`: scheduled lifecycle queued→running→complete
visible via `/history`. **Gate:** `make migrate` 0012 up+down.

---

### Phase 4 — Per-category digest summaries ★ (headline; race-free, run-scoped)

**Goal:** one synthesized rollup per non-empty category per run, built **only from the complete per-email set**.

**Build:**
- **Migration `0013`:** nullable `summaries.run_id`+`category`; relax kind CHECKs to admit
  `kind='category_digest'` (both target FKs NULL, `run_id`+`category` NOT NULL); partial unique index
  `uq_summaries_run_category WHERE kind='category_digest'`. Reversible. Sync ORM.
- **Prompt** `category_digest/v1.md` + schema (Gemini Flash; input = the run+category's per-email TLDRs/
  key_points; output `{narrative, groups:[{label,bullets,item_refs}], confidence}`). `CategoryDigestSummary`
  Pydantic mirror.
- **Service** `summarization/category.py::summarize_category` — builds from the **complete** per-email set for
  `(run, category)`, via `LLMClient.call` (inherits USD cap + fallback). **Repo** `upsert_category_digest` + `decrypt_category_*`.
- **Race-free trigger:** category digests are built **only after the run's classify + per-email summarize is
  fully drained** (`pending_unclassified == 0 and pending_summaries == 0`), then **once** per `(run, category)`.
  Finalization, on detecting a drained run with a non-empty category whose digest row is missing, enqueues a
  `CategoryDigestMessage{run_id, category}` (new frozen message kind on the existing **summarize queue** — no
  new queue; built inline in local/test where no queue is configured). `_pending_category_summaries` holds the
  run in `running` until the digest rows exist; then `pending_total==0` → `complete`. The unique index is a
  dup-safety net. **No digest is ever built from a partial set** (fixes the "first-summary then index-locked"
  race). A permanently-failed per-email summary marks the run `failed` via the existing `prompt_errors` path —
  no hung or partial digest.
- **API:** extend `DigestTodayResponse` (+`category_summaries`, default `()`; + a `rule_decided` count of
  `decision_source='rule'` classifications for the **D7** stat); selector loads the latest complete run's
  digests (must_read first). `make docs`.

**Cost:** ≤2 extra Gemini Flash calls/run (short TLDR input).

**Test cases:** schema validation; repo round-trip (cipher None + fake KMS) + re-upsert in place (one row);
**trigger fires only when `pending_unclassified==0 AND pending_summaries==0`, never on a partial set**;
idempotency (twice → 1 call, 1 row); a permanently-failed per-email summary → run `failed`, no partial digest;
finalization stays `running` until the digest exists; `digest/today` returns decrypted summaries, must_read
first. **Gate:** `make migrate` 0013 up+down.

---

### Phase 5 — Mark-as-read backend + unread-only scan  *(write scope; precedes the UI)*

**Goal:** clear reviewed mail out of Gmail and guarantee it never reappears.

**Build:**
- **New ADR** amending ADR 0006 (recommend-only) + ADR 0007 (mailbox provider): permit the single, explicit,
  user-initiated, reversible removal of the `UNREAD` label; no delete/archive/send.
- **Scope:** add `gmail.modify` to the scope tuple ([gmail/oauth.py:42](backend/app/services/gmail/oauth.py));
  re-authorize the 3 accounts (re-consent flow). Document the broader scope (Gmail has no labels-only scope).
- **Provider:** extend `MailboxProvider` ([domain/providers.py](backend/app/domain/providers.py)) with
  `mark_read(message_ids) -> MarkReadResult`; Gmail impl calls `users.messages.batchModify`
  (`removeLabelIds:["UNREAD"]`), code-restricted to UNREAD, per-account batched, idempotent, partial-failure-safe.
- **Endpoint (only new one):** `POST /api/v1/emails/mark-read` `{email_ids?: UUID[], category?, account_id?}` —
  per-email and select-all-in-category; ownership-checked; updates local `emails.labels` (drop UNREAD);
  returns `{marked, failed}`. No new column.
- **Unread-only scan (both code paths):** flip `scan.unread_only=true`. **(a)** the `list_messages` bootstrap
  query → `is:unread newer_than:{lookback}d`. **(b)** the **`list_history` incremental path**
  ([provider.py:78-90](backend/app/services/gmail/provider.py)) has no server-side unread filter, so **filter
  fetched history messages to those still bearing `UNREAD`** (drop a history-added message that isn't unread).
- **Read models filter to UNREAD:** digest counts, `GET /emails`, must_read_preview, and the category-digest
  source set exclude emails whose `labels` lack `UNREAD`. mark-read drops `UNREAD` locally + in Gmail, so a
  marked-read email **leaves every Briefed view and never reappears in subsequent scans**. Reuses `labels` — no new column.

**Test cases:** provider `mark_read` batchModify (UNREAD only), idempotent, partial-failure; scope includes
`gmail.modify`; endpoint by ids and by `category`, ownership 404, pre-re-consent → clear "re-authorize" error.
**No-reappear:** after mark-read, a subsequent scan (mocked unread query) does not re-surface it and it's
absent from `/emails` + counts. **History path:** a history-added message *without* `UNREAD` is filtered out.
**Gate:** ADR merged; re-consent verified on one real dev account.

---

### Phase 6 — PWA single Dashboard + Settings + layout  *(consumes the finished backend)*

**Goal:** the Dashboard is the brief; all config in Settings; wide, responsive, compact forms.

**Build (DESIGN.md tokens only):**
- **Single Dashboard** ([DashboardPage.tsx](frontend/src/pages/DashboardPage.tsx)): (1) per-category
  **narrative summary** cards from `category_summaries` via **`SafeMarkdown`** (Must-Read heading `text-accent`;
  newsletters fold into the Good-to-Read summary); (2) **KPI cards** (All · Must-Read · Good-to-Read · Ignore)
  from `digest/today` that **filter** (3) a **paginated email table** (`GET /emails?bucket=&offset=&limit=`)
  where **each row shows a category tag** + sender/subject/received/summary, with per-row + **bulk select-all
  mark-read** (`POST /emails/mark-read`, already live); plus Scan-now, freshness, cost, **D2** low-confidence badge, **D7** rules-sorted stat.
  Remove the `/must-read|good-to-read|ignore|jobs` routes.
- **Settings — all config:** tabs **Accounts · Schedule · Rules · Preferences**. **Schedule**
  ([settings/SchedulePage.tsx](frontend/src/pages/settings/SchedulePage.tsx)): compact form for
  `schedule_frequency` (once/twice/disabled) + `schedule_times_local[]` + timezone, wired to
  `GET/PATCH /api/v1/profile/me/schedule` (backend exists in [profile.py](backend/app/api/v1/profile.py); fix it
  if it currently reads `preferences.digest_send_hour_utc`). **Rules:** form editor over `/api/v1/rubric` CRUD
  (sender email/domain, subject contains/regex, Gmail label, topic keyword → category/confidence + `name`);
  retire the raw-JSON Prompts page. Fix the account-status vocabulary mismatch.
- **Layout — wide + responsive + compact forms:** widen data screens and use **2–3 column** responsive form
  grids (1 col `<md`, 2 `md`, 3 `lg/xl`); keep narrative text width-capped. **Update DESIGN.md §5/§9 in the
  same change** (CLAUDE.md §10): add `--container-wide` (~1440px, fluid w/ gutters), widen Settings to ~960px,
  add `--measure` (~72ch). Use existing `--space-*` + breakpoints `sm/md/lg/xl`.
- Offline: Workbox already matches `/api/v1/digest*` — no change.

**Test cases (vitest):** narrative cards render; empty `[]` → summaries hidden, table still renders; **KPI click
filters the table** (`?bucket=` updates; "All" clears); **pagination** (offset) changes page; **row category tag**;
rule editor CRUD; schedule form reads/writes `/profile/me/schedule`; mark-read per-row + bulk select-all
(optimistic); 2–3 col grid at `md`/`lg`; `NAV_ITEMS` has none of `/jobs`,`/must-read`,`/good-to-read`,`/ignore`.
`make lint`/`format:check` clean; both themes (DESIGN.md §12).

---

## 8. Migration & schema sequencing

```
Phase 0  (no migration)  — config + catalog.yml; behavior-neutral
Phase 1  0010  — classifications.needs_review; remap labels; zero is_job_candidate; CHECK→3; rubric_rules.name
Phase 2  0011  — drop job_matches / job_filters / classifications.is_job_candidate
Phase 3  0012  — digest_run_emails (run membership)
Phase 4  0013  — summaries.run_id + category; relaxed CHECK; partial unique index
Phase 5  (no migration)  — mark-read reuses emails.labels; unread scan is query/filter logic
Phase 6  (no migration)  — frontend + DESIGN.md tokens
```

`runs.py::pending_total` evolves: Phase 2 removes the `pending_jobs` term → Phase 3 makes all pending checks
**run-scoped** (join `digest_run_emails`) → Phase 4 adds `pending_category_summaries` (gated so the digest is
built only when the run is otherwise drained). Run `make migrate` up **and** down on Postgres after each
migration (pytest uses SQLite `create_all`, not Alembic).

---

## 9. Risks & gates

| Risk | Mitigation |
|---|---|
| Digest built from a partial set (race) | Category digest fires only when `pending_unclassified==0 AND pending_summaries==0`, once per `(run,category)`; unique index is a dup safety-net. Dedicated trigger test. |
| Run never finalizes / stale leftovers | Phase 3 run-scopes finalization via `digest_run_emails`; Phase 2 removes the jobs term; zero-new runs finalize. |
| `reclassify_recent` over old mail | Membership table records the run's target emails explicitly (not a `created_at` heuristic). |
| Marked-read mail reappears | Phase 5 unread-only scan (query **and** history filter) + read-models filter to UNREAD; mark-read drops UNREAD locally + in Gmail. History-path test included. |
| Gmail write scope over-reach | Code-restricted to UNREAD removal; explicit user action; reversible; new ADR; ownership-checked. |
| Silent prod misconfig | `app_config.yml` + `catalog.yml` **fail hard in Lambda**; only local/test falls back to defaults. |
| `LLMClient` 100% coverage pin | catalog.yml loader keeps `resolve`/`chain` stable; Presidio is injected, not imported, in client.py. Verify `make coverage`. |
| Prompt↔model drift | `PromptSpec.model` validated against `ModelCatalog` keys at boot; registry tests updated. |
| OpenAPI drift | Every schema/route change → `make docs` (CI `docs-drift` gate). |
| ADR immutability | Presidio removal + mark-read each get a **new superseding ADR**; never edit 0006/0007/0010. |
| Migrations untested by pytest | `make migrate` up+down on Postgres; `op.batch_alter_table` for SQLite-portable CHECK swaps. |
| Layout vs calm aesthetic | New `--container-wide`/`--measure` tokens update DESIGN.md §5/§9 in-change; narrative text stays width-capped. |
| Plan location (dual governance) | Canonical copy kept in **both** `.claude/plans/` and `.Codex/plans/`, identical. |
| README staleness | pyyaml add, presidio removal, config files, new endpoint, scope change → README/.env.example in-change. |

---

## 10. End-to-end verification

1. **Local:** `docker compose up -d`; `make bootstrap`; seed mailbox; `POST /runs`; poll to `complete`;
   `GET /digest/today` returns non-empty `category_summaries`.
2. **Run boundaries:** a second run with no new mail finalizes; a `reclassify_recent` run re-triages only its
   membership set; a scheduled run appears in `/history`.
3. **Models:** edit `catalog.yml` (bump a route) → calls use it, no code change; a bad key fails at boot.
4. **Quality:** `make eval` triage v2 + category_digest meet thresholds.
5. **CI:** `make ci` green (lint, mypy --strict, pytest, vitest, coverage ≥80%, docs-drift, security, tf).
6. **Migrations:** `make migrate` up→head then down→base clean on Postgres.
7. **Mark-read / no-reappear:** re-consent one dev account; mark an Ignore item read → it leaves Gmail UNREAD,
   disappears from the table, and a re-scan does not bring it back (incl. the history path).
8. **PWA:** `make dev`; narrative cards via SafeMarkdown; KPI cards filter the paginated tagged table; bulk
   mark-read on Ignore; Schedule + Rules forms; no removed routes; install as PWA + offline read; both themes.
9. **Live daily check:** dev deploy via GitHub Actions; connect 3 accounts; let the schedule fire; confirm a
   real brief + a visible scheduled run; watch ~3 days; cost ≈ near-zero; alarms quiet.

---

## 11. Out of scope (future)

Email/push delivery (PWA-only chosen); learning rules from your actions (D6); a 4th "Respond vs FYI" category
(D3); IMAP/Outlook providers; re-introducing jobs (reversible via the 0011 down-migration + `features.jobs`).

---

## 12. Critical files

**Config/LLM:** [core/app_config.py](backend/app/core/app_config.py) *(new)* + `packages/config/app_config.yml`
+ `packages/config/llm/catalog.yml` *(new)*; [llm/catalog.py](backend/app/llm/catalog.py) (YAML loader, stable API);
prompt registry validation.

**Pipeline/runs:** [services/runs.py](backend/app/services/runs.py) (jobs term out, run-scoped via membership,
category term in); `db/models.py` (Classification CHECK + `needs_review`; Summary new kind/cols; `rubric_rules.name`;
**`digest_run_emails`**; drop Job*); [classification/pipeline.py](backend/app/services/classification/pipeline.py)
+ [rubric.py](backend/app/services/classification/rubric.py); [summarization/category.py](backend/app/services/summarization/category.py)
*(new)* + repository.py; [workers/messages.py](backend/app/workers/messages.py) (`CategoryDigestMessage`);
[lambda_worker.py](backend/app/lambda_worker.py) (remove jobs enqueue; category-digest trigger).

**Mailbox/scan:** [domain/providers.py](backend/app/domain/providers.py) + [gmail/oauth.py](backend/app/services/gmail/oauth.py)
(`mark_read` + `gmail.modify`); [gmail/provider.py](backend/app/services/gmail/provider.py) (unread-only: query +
history filter); [api/v1/emails.py](backend/app/api/v1/emails.py) (filters/offset + mark-read);
[api/v1/profile.py](backend/app/api/v1/profile.py) (schedule).

**API/schema:** [schemas/frontend.py](backend/app/schemas/frontend.py) + [api/v1/frontend.py](backend/app/api/v1/frontend.py)
(`category_summaries`); [workers/handlers/fanout.py](backend/app/workers/handlers/fanout.py) (DigestRun).

**Migrations:** `0010`–`0013` in [backend/alembic/versions/](backend/alembic/versions/).

**Prompts:** `triage/v2.*`, `category_digest/v1.*`; frontmatter model keys updated across bundles.

**Frontend:** [DashboardPage.tsx](frontend/src/pages/DashboardPage.tsx), [settings/SchedulePage.tsx](frontend/src/pages/settings/SchedulePage.tsx),
rule-editor page, `router.tsx`, `shell/navItems.ts`, [tokens.css](frontend/src/styles/tokens.css).

**Docs:** new ADRs (Presidio removal; mark-read write scope), [DESIGN.md](DESIGN.md) (§5/§9), [README.md](README.md),
`.env.example`, this plan (both plan dirs).
