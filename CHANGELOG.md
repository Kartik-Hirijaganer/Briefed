# Changelog

All notable changes to Briefed are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Commit convention: [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added

- Phase 7 offline + mobile polish (plan §14 Phase 7, §19.16):
  - Workbox runtime caching for digest, email-list, jobs, news,
    unsubscribe, history, and immutable summary reads.
  - Dexie-backed TanStack Query persistence in IndexedDB for cold
    offline opens, with a 7-day cache window.
  - Durable `pending_mutations` queue with replay-on-reconnect and a
    `<QueuedActionsSheet>` for inspecting, cancelling, and manually
    retrying queued actions.
  - Offline-aware optimistic mutations for account toggles, preferences,
    unsubscribe dismiss/confirm, and email bucket changes.
  - Swipe gestures on email cards, dashboard pull-to-refresh wired to
    Scan Now, iOS install prompt display, storage-pressure warning, and
    Android-only haptic completion feedback.

- Phase 6 frontend PWA + dashboard + triage + settings (plan §14 Phase 6,
  §10 IA, §19.16):
  - `@briefed/ui` primitive library: `Button` (discriminated-union variant
    props), `Field` (a11y label + description + error wiring), `Switch`,
    `Card`, `Dialog`, `Sheet`, `EmptyState`, `Skeleton`, `ErrorState`,
    `Alert`, `Badge`, `FreshnessBadge`, `WhyBadge` (§19.8 explainability),
    `OpenInGmailLink`, `InstallPromptIOS`, and an upgraded `Motion` helper
    wired to framer-motion with `useReducedMotion` collapse.
  - `@briefed/contracts` exposes a barrel `index.ts` and an `exports` map
    so the OpenAPI JSON and provider types resolve from both sides.
  - Root `package.json` turns the repo into an npm workspace covering
    `frontend`, `packages/ui`, `packages/contracts`.
  - Vite + React 18 + TypeScript strict frontend (`frontend/`):
    Tailwind v4 wired against the `@briefed/ui` tokens, typed API client
    on top of `openapi-fetch` with session-cookie credentials + CSRF
    double-submit + 401 redirect middleware, TanStack Query with a 7-day
    GC default, and `vite-plugin-pwa` precaching the app shell.
  - Hooks `useBreakpoint`, `useOnlineStatus`, `useFreshnessState` (plan
    §19.8 four named states), and `useRunProgress` (polling-only per
    §20.6).
  - Routes matching §10 IA: dashboard, `/must-read`, `/good-to-read`,
    `/ignore`, `/waste`, `/jobs`, `/news`, `/unsubscribe`, `/history`,
    `/settings/{accounts,preferences,prompts,schedule}`, `/login`, and
    `/oauth/callback`, rendered inside an `<AppShell>` with sidebar
    (≥ md) + `<BottomTabBar>` (mobile).
  - Settings → Accounts owns Add Gmail, per-account auto-scan toggle,
    disconnect confirm dialog, and a mobile bottom `<Sheet>` for the
    overflow menu (§19.16 §1 + §6). Preferences owns the global
    auto-execution toggle (§19.16 §2) plus PII-redaction and
    secure-offline toggles.
  - Dashboard hosts the Scan Now button per §19.16 §3: manual run via
    `POST /api/v1/runs`, polling `GET /api/v1/runs/{id}` through
    `useRunProgress`, offline guard, success auto-revert.
  - Vitest component tests: `<Button>` discriminated-union + click +
    loading (with `@ts-expect-error` regression cases), `<Field>` a11y
    attributes and required marker.
  - Frontend TS contract stub at `src/api/schema.d.ts`; `make docs`
    regenerates via `npm run codegen` (`openapi-typescript`).
- Phase 5 unsubscribe + inbox hygiene (plan §14 Phase 5):
  - `app.services.unsubscribe.parser` — lenient RFC 2369 / RFC 8058
    `List-Unsubscribe` parser. Handles bracketed entries, bare
    whitespace/comma fallbacks, mailto / http / https classification,
    URL + entry caps, and RFC 8058 one-click POST detection. Pure-
    functional so it slots into any future mailbox provider.
  - `app.llm.schemas.UnsubscribeDecision` — Pydantic mirror of the
    borderline LLM output with `extra="forbid"` covering
    `should_recommend` / `confidence` / `category` (controlled enum) /
    `rationale`.
  - `packages/prompts/unsubscribe_borderline/v1.md` +
    `packages/prompts/schemas/unsubscribe_borderline.v1.json` —
    versioned prompt + JSON Schema with `<untrusted_sample>`
    delimiters, calibrated-confidence guidance, and a hard contract
    against auto-acting (ADR 0006 recommend-only).
  - `app.services.unsubscribe`:
    - `aggregator.py` — SQL aggregate over `emails` × `classifications`
      (trailing 30 days) that computes per-sender `frequency_30d`,
      `engagement_score`, `waste_rate`, and latest `List-Unsubscribe`
      target. `score_sender` maps signals onto three rule criteria
      (noisy / low_value / disengaged); `rank_senders` is the
      orchestrator — 3-of-3 → rule-only recommendation at 0.9
      confidence; exactly 2-of-3 → borderline LLM call; ≤1 → skipped.
      An LLM veto caps the persisted confidence below the policy
      gate so the UI hides the row while keeping an audit trail.
    - `repository.py` — `UnsubscribeSuggestionsRepo` with transparent
      envelope encryption on `rationale` per §20.10; metadata stays
      plaintext so the hygiene-stats endpoint can aggregate without
      KMS round-trips. Upsert preserves `dismissed` + `dismissed_at`
      across re-runs so dismissals survive the next aggregate.
    - `dispatch.py` — `enqueue_hygiene_run_for_account` emits one
      `UnsubscribeMessage` per account per run; `parse_unsubscribe_body`
      validates the SQS body.
  - `app.workers.handlers.unsubscribe.handle_unsubscribe` SQS handler
    + `_handle_unsubscribe_record` wiring in `lambda_worker` (routes
    the `unsubscribe` queue to the hygiene aggregator). The classify
    handler opportunistically enqueues a hygiene run when
    `BRIEFED_UNSUBSCRIBE_QUEUE_URL` is set (idempotent per-account
    upsert protects against duplicate SQS messages).
  - SQLAlchemy ORM + Alembic `0005_phase5_unsubscribe_suggestions`
    migration for `unsubscribe_suggestions` (envelope-encrypted
    `rationale_ct`, unique on `(account_id, sender_email)`, check
    constraints on all ratios + `decision_source IN ('rule', 'model')`).
  - API:
    - `GET /api/v1/unsubscribes` — top-N recommendations,
      confidence-desc, dismissed rows hidden by default
      (`include_dismissed=true` opts in).
    - `POST /api/v1/unsubscribes/{id}/dismiss` — persist dismissal;
      aggregate re-runs preserve the flag.
    - `POST /api/v1/unsubscribes/{id}/confirm` — recommend-only
      confirm; dismisses the row without touching Gmail.
    - `GET /api/v1/hygiene/stats` — total-candidate counter,
      dismissed count, average frequency, top sender domains.
  - New `UnsubscribeMessage` SQS payload + per-file N803 ignore for
    the dispatch protocol kwargs.
  - Tests (38 unit + 14 integration — 318 total, 84% coverage):
    - `test_unsubscribe_parser` — 22-case matrix covering mailto,
      https, http fallback, one-click RFC 8058, bracketless entries,
      duplicates, scheme filtering, and the URL-length / entry-count
      caps.
    - `test_unsubscribe_scoring` — rule-engine threshold checks
      (3-hit / 2-hit / 1-hit / empty-classification-set) +
      `UnsubscribeDecision` extra-fields rejection + rationale trim.
    - `test_unsubscribe_repo` — upsert inserts + replaces + preserves
      user-side dismissal across re-runs.
    - `test_unsubscribe_aggregate` — per-sender aggregate correctness,
      rule + model branches coexisting, LLM-veto confidence capping.
    - `test_unsubscribe_dispatch` — enqueue + body roundtrip + body
      reject + handler happy path + missing-prompt-version raises.
    - `test_unsubscribes_api` — confidence-desc ordering, dismiss
      hides rows by default, cross-user isolation, dismiss requires
      ownership, hygiene-stats counters + top domains, 401 without a
      session cookie.
- New optional env var `BRIEFED_UNSUBSCRIBE_QUEUE_URL` for the
  Phase 5 hygiene queue (+ `BRIEFED_SUMMARIZE_QUEUE_URL` and
  `BRIEFED_JOBS_QUEUE_URL` are now documented alongside it in
  `.env.example`).

- Phase 4 job extraction + filters (plan §14 Phase 4):
  - `app.llm.schemas.JobMatch` — Pydantic mirror with `extra="forbid"`
    covering title / company / location / remote (tri-state) /
    comp_min/max / currency / comp_phrase / seniority (controlled enum) /
    source_url / match_reason / confidence.
  - `packages/prompts/jobs/v1.md` + `packages/prompts/schemas/job_extract.v1.json`
    — versioned extractor prompt with the hallucination-guard contract
    (every numeric salary must cite a verbatim `comp_phrase` lifted
    from the body).
  - `app.services.jobs`:
    - `predicate.py` — pure-functional JSONB predicate engine
      (`min_comp`, `max_comp`, `currency`, `remote_required`,
      `location_any`, `location_none`, `title_keywords_any`,
      `title_keywords_none`, `seniority_in`, `min_confidence`) with
      whitelist enforcement so a typo'd operator never widens a filter.
    - `repository.py` — `JobMatchesRepo` with transparent envelope
      encryption of `match_reason` per §20.10; metadata stays
      plaintext so the predicate engine does not need KMS on the
      filter hot path.
    - `extractor.py` — `extract_job` end-to-end: render prompt → call
      `LLMClient` → `corroborate_comp` (regex-verifies salary numbers
      against the source body; hallucinations are sanitized and the
      confidence is capped below the digest floor) → evaluate every
      active `JobFilter` → upsert the row with `passed_filter` +
      `filter_version`.
    - `dispatch.py` — `enqueue_unextracted_for_account` enqueues one
      `JobExtractMessage` per un-extracted `job_candidate`.
  - `app.workers.handlers.jobs.handle_job_extract` SQS handler.
  - SQLAlchemy ORM + Alembic `0004_phase4_job_extraction_tables`
    migration for `job_matches` (envelope-encrypted
    `match_reason_ct`) and `job_filters` (JSONB `predicate`). Check
    constraints enforce `comp_min <= comp_max` and currency-required-
    when-comp-is-set.
  - New `JobExtractMessage` SQS payload + `parse_job_extract_body`
    validator, mirroring the classify/summarize queue patterns.
  - Promptfoo golden set: `backend/eval/golden/job_extract_v1.jsonl`
    (10 canonical fixtures spanning remote / on-site / hybrid,
    multiple currencies, seniority tiers, and low-confidence
    recruiter pings). Added as a new `job_extract` suite in
    `backend/eval/promptfoo.yaml`.
  - Tests (unit + integration):
    - `test_job_match_schema` — `extra="forbid"`, currency
      normalization, confidence bounds, seniority enum, JSON-schema
      parity with the Pydantic mirror.
    - `test_job_predicate` — full operator matrix + remote tri-state
      + unknown-key rejection + malformed-value guard.
    - `test_job_matches_repo` — KMS round-trip, pass-through mode,
      upsert replaces-in-place, empty-reason round-trip.
    - `test_job_corroboration` — salary guard accepts verbatim
      phrases, tolerates normalized whitespace, sanitizes
      hallucinated numbers, noop when no comp was returned.
    - `test_job_extract_pipeline` — happy path (encrypted reason +
      `passed_filter=True`), hallucinated salary (row persisted with
      comp cleared + `passed_filter=False`), predicate rejection,
      LLM exhaustion (no row written + `error` call-log row).
    - `test_job_extract_dispatch` — picks unextracted rows, skips
      non-`job_candidate`, round-trips `JobExtractMessage`.
    - `test_job_extract_handler` — handler end-to-end + missing
      `prompt_versions` row raises `LookupError` for SQS redelivery.

- Phase 2 classification + rubric + prompt registry (plan §14 Phase 2):
  - `app.llm` package:
    - `schemas.py` — `TriageDecision` Pydantic model with
      `extra="forbid"` so any hallucinated field raises at the
      boundary.
    - `providers/` — `LLMProvider` protocol (plan §19.4),
      `GeminiProvider` (primary — Gemini 1.5 Flash per §20.1) and
      `AnthropicDirectProvider` (gated Claude Haiku 4.5 fallback).
    - `client.py` — `LLMClient` facade with retries (exponential
      backoff + jitter), `CircuitBreaker`, configurable fallback
      chain, per-provider `RateCap` (100/day Anthropic cap), prompt
      rendering, and async `PromptCallRecord` persistence hook.
  - `app.services.prompts.registry` — loads versioned prompt bundles
    from `packages/prompts/**/v*.md`, validates YAML frontmatter,
    and upserts rows into `prompt_versions` so `prompt_call_log` FKs
    resolve.
  - `packages/prompts/triage/v1.md` + `packages/prompts/schemas/triage.v1.json`
    — the first versioned prompt with `<untrusted_email>` delimiters
    (prompt-injection hardening per §19.9).
  - `app.services.classification`:
    - `rubric.py` — `RuleEngine` over `rubric_rules` +
      `known_waste_senders` with priority ordering and seed-level
      short-circuits.
    - `repository.py` — `ClassificationsRepo` with transparent
      envelope encryption of `classifications.reasons` per §20.10.
    - `pipeline.py` — rule-first, LLM-on-miss orchestrator that
      writes `classifications` + `prompt_call_log` rows (`ok` /
      `fallback` / `skipped` / `error`).
    - `dispatch.py` — enqueues one `ClassifyMessage` per
      un-classified email onto the classify SQS queue.
  - `app.core.content_crypto` — `content_context()` helper binding
    `{table, row_id, purpose, user_id}` into every KMS Encrypt /
    Decrypt call (plan §20.10).
  - `app.workers.handlers.classify.handle_classify` + lambda dispatcher
    route for the `classify` stage.
  - API: `GET/POST/PUT/DELETE /api/v1/rubric` (`app.api.v1.rubric`)
    — user-editable classification rules with predicate-key and
    action-value validation at the boundary; `version` auto-bumps on
    update.
  - SQLAlchemy ORM + Alembic `0002_phase2_classification_tables`
    migration for `classifications`, `rubric_rules`,
    `prompt_versions`, `prompt_call_log`, `known_waste_senders` plus
    seed rows for `known_waste_senders`.
  - Promptfoo scaffolding: `backend/eval/promptfoo.yaml`,
    `backend/eval/thresholds.yaml`, and golden-set seeds at
    `backend/eval/golden/triage_v1.jsonl` +
    `backend/eval/golden/triage_v1_adversarial.jsonl`.
  - Tests: unit (`TriageDecision` forbid, rubric precedence,
    prompt-registry parsing, LLM client retry + circuit breaker +
    fallback + rate cap, content-crypto context, triage-schema
    contract) and integration (pipeline rule-only / LLM /
    fallback / low-confidence demotion / rubric propagation,
    classify dispatch, rubric-API CRUD).
- New optional env var `BRIEFED_CLASSIFY_QUEUE_URL` so the ingest
  handler enqueues classify jobs for newly ingested emails.

- Phase 1 Gmail auth + ingestion:
  - `app.domain.providers.MailboxProvider` protocol + Pydantic boundary
    objects (`EmailMessage`, `EmailBody`, `RawMessage`, `SyncCursor`,
    `ProviderCredentials`, `UnsubscribeInfo`) — the seam the ingestion
    pipeline depends on, not the concrete `GmailProvider`.
  - SQLAlchemy ORM models + the `0001_phase1_ingestion_tables` Alembic
    migration for `users`, `connected_accounts`, `oauth_tokens`,
    `sync_cursors`, `emails`, `email_content_blobs`.
  - Async SQLAlchemy engine + session factory (`NullPool` for Supabase
    pooler reuse per plan §19.15).
  - Envelope-crypto helper (`app.core.security`) with KMS-CMK wrapping
    per §20.3 — 100% unit-test coverage.
  - `app.services.gmail`:
    - `parser.py` — MIME → `EmailMessage` (List-Unsubscribe,
      multipart/alternative, encoded-word subjects, quoted-reply trim).
    - `client.py` — Gmail REST client with a per-account token-bucket
      (`ratelimit.py`) and tenacity-retry on 429 / 5xx.
    - `oauth.py` — OAuth authorization-code flow helpers (PKCE,
      authorize URL, token exchange / refresh / revoke).
    - `provider.py` — `GmailProvider` implementation of `MailboxProvider`.
  - `app.services.ingestion`:
    - `dedup.py` — content-hash + `UNIQUE(account_id, gmail_message_id)`
      idempotency (100% unit-test coverage).
    - `storage.py` — optional S3 raw-MIME upload toggle.
    - `pipeline.py` — orchestrator tying provider + parser + dedup +
      storage + cursor persistence into one `IngestStats` result.
  - API routers at `/api/v1`: `oauth/gmail/start|callback` + `accounts`
    (list + delete). Signed-cookie session via `app.api.session`.
  - Worker handlers: `app.workers.handlers.fanout.run_fanout` (enqueues
    one `IngestMessage` per active account) + `handlers.ingest.handle_ingest`
    (decrypt tokens → run pipeline → persist). `lambda_worker` routes
    SQS records by queue-ARN tail and reports `batchItemFailures`.
  - Tests: 100 tests across unit + integration — MIME parser fixtures,
    envelope-crypto roundtrip, dedup scenarios, 100-email ingest with
    UNIQUE enforcement + no-op re-run, simulated 429 → retry success,
    stale-cursor bounded full-sync fallback, e2e OAuth start → callback
    → `/api/accounts` listing the new account.
- New required env var `BRIEFED_INGEST_QUEUE_URL` (+ optional
  `BRIEFED_STORE_RAW_MIME`) for the fan-out handler.
- Python dependencies added: `email-validator`, `aiosqlite` (dev),
  `greenlet` (transitively required by SQLAlchemy async).

- Phase 0 foundation: `packages/` monorepo layout (contracts, prompts,
  config, ui), initial ADR set (0001–0008), Terraform modules for Lambda
  + SnapStart + SQS + SSM + S3 + CloudFront + Route 53 + ACM + two
  customer-managed KMS CMKs, docker-compose for local Postgres + LocalStack,
  GitHub Actions CI workflow with lint / test / coverage / docs-drift /
  security / terraform jobs, `Makefile` with the canonical developer
  commands (`make test`, `make docs`, `make lint`, `make coverage`,
  `make dev`, `make migrate`, `make bootstrap`, `make deploy-dev`), and
  docs scaffolding (`docs/architecture/`, `docs/operations/`,
  `docs/security/`, `docs/contributors/`).
- Lambda entry-point stubs for SnapStart (`backend/app/lambda_api.py` +
  `backend/app/lambda_worker.py`).
- Phase 0 closure (auditing gaps against plan §14 + §19.15 + §20.6):
  - `backend/Dockerfile` — AWS Lambda container image (Python 3.11 base)
    consumed by the `deploy-dev` workflow.
  - `backend/app/core/config.py` — typed `Settings` via `pydantic-settings`
    with SSM Parameter Store hydration on cold-start; rejects missing /
    placeholder required parameters with `MissingSecretError`.
  - `backend/app/core/logging.py` — idempotent structlog JSON setup.
  - `backend/app/integrations/ssm_secrets.py` — thin SSM adapter.
  - Alembic scaffolding under `backend/alembic/` + `backend/alembic.ini`
    so Phase 1 can land the first migration immediately.
  - `deploy-dev.yml` — ECR-autocreate step + cleaner step ordering; Mangum
    handler + SSM loader now initialize at module import for SnapStart.
  - Phase 0 exit-criteria tests: `tests/unit/test_config.py` (rejects
    missing SSM parameters) and `tests/integration/test_lambda_api.py`
    (Lambda Function URL event returns `/health` 200).

### Changed

- `pyproject.toml` now declares the Phase 0 Python dependencies
  (SQLAlchemy, Alembic, asyncpg, boto3, mangum, google-generativeai,
  structlog, tenacity, pybreaker, OpenTelemetry) plus the 80% coverage
  gate from plan §20.1.

[Unreleased]: https://github.com/Kartik-Hirijaganer/Briefed/compare/main...HEAD
