# Changelog

All notable changes to Briefed are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Commit convention: [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added

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
