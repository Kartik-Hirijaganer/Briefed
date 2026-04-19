# Changelog

All notable changes to Briefed are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Commit convention: [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added

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

### Changed

- `pyproject.toml` now declares the Phase 0 Python dependencies
  (SQLAlchemy, Alembic, asyncpg, boto3, mangum, google-generativeai,
  structlog, tenacity, pybreaker, OpenTelemetry) plus the 80% coverage
  gate from plan §20.1.

[Unreleased]: https://github.com/Kartik-Hirijaganer/Briefed/compare/main...HEAD
