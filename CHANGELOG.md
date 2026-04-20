# Changelog

All notable changes to Briefed are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Commit convention: [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added

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
