# Briefed — top-level Makefile.
#
# Canonical developer commands per plan §19.17 (scope amended by §20.6 —
# ERD generation dropped, coverage floor is 80%).
#
# All CI workflows call these targets; there is one source of truth.

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

# Directories created by test runs / coverage / docs export. Stay in .artifacts/
# so clean-up is a single rm -rf.
ARTIFACTS_DIR := .artifacts
COV_BE_XML    := $(ARTIFACTS_DIR)/coverage-be.xml
COV_FE_LCOV   := frontend/coverage/lcov.info

COVERAGE_FLOOR ?= 80
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else printf '%s' python3; fi)
PIP ?= $(PYTHON) -m pip
ALEMBIC ?= $(PYTHON) -m alembic
BANDIT ?= $(PYTHON) -m bandit
MYPY ?= $(PYTHON) -m mypy
PIP_AUDIT ?= $(PYTHON) -m pip_audit
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
UVICORN ?= $(PYTHON) -m uvicorn
VULTURE ?= $(PYTHON) -m vulture
PROMPTFOO ?= npx --yes promptfoo@0.121.13
INFISICAL ?= infisical

export PYTHONPATH := backend:$(PYTHONPATH)

# ``.env`` is allowed only for Infisical selector metadata. Application
# secrets must live in Infisical and be injected through ``infisical run``.
ifneq (,$(wildcard .env))
include .env
endif
ifeq ($(strip $(BRIEFED_ENV)),)
BRIEFED_ENV := local
endif
ifeq ($(strip $(BRIEFED_RUNTIME)),)
BRIEFED_RUNTIME := local
endif
ifeq ($(strip $(LOG_LEVEL)),)
LOG_LEVEL := info
endif
ifeq ($(strip $(AWS_REGION)),)
AWS_REGION := us-east-1
endif
ifeq ($(strip $(AWS_ENDPOINT_URL)),)
AWS_ENDPOINT_URL := http://localhost:4566
endif
ifeq ($(strip $(AWS_ACCESS_KEY_ID)),)
AWS_ACCESS_KEY_ID := test
endif
ifeq ($(strip $(AWS_SECRET_ACCESS_KEY)),)
AWS_SECRET_ACCESS_KEY := test
endif
ifeq ($(strip $(BRIEFED_INFISICAL_PROJECT_ID)),)
BRIEFED_INFISICAL_PROJECT_ID := cbd87e9b-3963-4906-b8cc-d479ff5192ed
endif
ifeq ($(strip $(BRIEFED_INFISICAL_ENVIRONMENT)),)
BRIEFED_INFISICAL_ENVIRONMENT := dev
endif
ifeq ($(strip $(BRIEFED_INFISICAL_SECRET_PATH)),)
BRIEFED_INFISICAL_SECRET_PATH := /development
endif
ifeq ($(strip $(BRIEFED_INFISICAL_DOMAIN)),)
BRIEFED_INFISICAL_DOMAIN := https://app.infisical.com/api
endif
LOCAL_RUN_ENV = BRIEFED_ENV=$(BRIEFED_ENV) BRIEFED_RUNTIME=$(BRIEFED_RUNTIME) LOG_LEVEL=$(LOG_LEVEL) AWS_REGION=$(AWS_REGION) AWS_ENDPOINT_URL=$(AWS_ENDPOINT_URL) AWS_ACCESS_KEY_ID=$(AWS_ACCESS_KEY_ID) AWS_SECRET_ACCESS_KEY=$(AWS_SECRET_ACCESS_KEY)
INFISICAL_RUN = $(LOCAL_RUN_ENV) $(INFISICAL) run --projectId $(BRIEFED_INFISICAL_PROJECT_ID) --env $(BRIEFED_INFISICAL_ENVIRONMENT) --path $(BRIEFED_INFISICAL_SECRET_PATH) --domain $(BRIEFED_INFISICAL_DOMAIN) --silent --
export BRIEFED_ENV BRIEFED_RUNTIME BRIEFED_INFISICAL_PROJECT_ID BRIEFED_INFISICAL_ENVIRONMENT BRIEFED_INFISICAL_SECRET_PATH

# Frontend scaffolding landed in Phase 6 (sources + tsconfig + primitives).
# CI still keys frontend-side targets off the lockfile so a clean clone
# without ``npm install`` does not break the gate — operators run
# ``make bootstrap`` once to create ``package-lock.json`` at the repo root
# (npm workspaces hoist deps across frontend/ + packages/).
FRONTEND_READY := $(shell test -f package-lock.json && echo 1)

.PHONY: help
help:
	@awk 'BEGIN{FS=":.*##"; printf "\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# --------------------------------------------------------------------------- #
# Bootstrap + dev loop                                                        #
# --------------------------------------------------------------------------- #

.PHONY: bootstrap
bootstrap: ## Install Python + Node deps and start docker-compose services
	$(PIP) install -e ".[dev]"
ifneq (,$(wildcard package.json))
	npm install
endif
	docker compose up -d
	@$(MAKE) _ensure-local-kms

.PHONY: dev
dev: bootstrap require-infisical _wait-postgres migrate ## Install deps, start services, fetch Infisical secrets, migrate DB, and run backend + frontend
	@if [ -f package-lock.json ]; then \
	  ( $(INFISICAL_RUN) $(UVICORN) app.main:app --app-dir backend --reload & \
	    npm --workspace frontend run dev & \
	    wait ); \
	else \
	  $(INFISICAL_RUN) $(UVICORN) app.main:app --app-dir backend --reload; \
	fi

.PHONY: require-infisical
require-infisical:
	@command -v $(INFISICAL) >/dev/null || (echo "Infisical CLI is required. Install it, then run 'infisical login'." && exit 1)
	@$(INFISICAL) login status --domain $(BRIEFED_INFISICAL_DOMAIN) --silent >/dev/null || (echo "Infisical CLI is not authenticated. Run 'infisical login'." && exit 1)

.PHONY: _ensure-local-kms
_ensure-local-kms:
	@$(LOCAL_RUN_ENV) $(PYTHON) backend/scripts/ensure_local_kms.py

.PHONY: _wait-postgres
_wait-postgres:
	@printf "==> Waiting for local Postgres"
	@for _ in {1..30}; do \
	  status=$$(docker inspect -f '{{.State.Health.Status}}' briefed-postgres 2>/dev/null || true); \
	  if [ "$$status" = "healthy" ]; then \
	    echo " ready"; \
	    exit 0; \
	  fi; \
	  printf "."; \
	  sleep 1; \
	done; \
	echo ""; \
	docker compose ps postgres; \
	echo "Postgres did not become healthy in time."; \
	exit 1

.PHONY: clean
clean: ## Remove build + test + coverage artifacts
	rm -rf $(ARTIFACTS_DIR) .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
	rm -rf frontend/coverage frontend/dist frontend/node_modules/.vite

# --------------------------------------------------------------------------- #
# Lint / format / type-check                                                  #
# --------------------------------------------------------------------------- #

.PHONY: lint
lint: ## Run all linters (Python + Frontend)
	$(RUFF) check .
	$(RUFF) format --check .
	$(MYPY)
ifdef FRONTEND_READY
	npm --workspace frontend run lint
endif
	@$(MAKE) lint-tokens

.PHONY: lint-tokens
lint-tokens: ## Fail if raw hex or rgb()/rgba() colors appear outside tokens.css (theme guard)
	@echo "==> lint-tokens: scanning frontend/src + packages/ui/src for hardcoded colors"
	@hits=$$(grep -rEn \
	  --exclude=tokens.css \
	  --exclude-dir=__tests__ \
	  --exclude='*.test.ts' --exclude='*.test.tsx' \
	  --exclude='*.spec.ts' --exclude='*.spec.tsx' \
	  '#[0-9a-fA-F]{3,8}|rgba?\(' \
	  frontend/src packages/ui/src 2>/dev/null); \
	if [ -n "$$hits" ]; then \
	  echo "lint-tokens: hardcoded color(s) found outside tokens.css — use DESIGN.md tokens:"; \
	  echo "$$hits"; \
	  exit 1; \
	fi; \
	echo "lint-tokens: OK (no hardcoded colors outside tokens.css)"

.PHONY: format
format: ## Apply formatters
	$(RUFF) format .
	$(RUFF) check --fix .
ifdef FRONTEND_READY
	npm --workspace frontend run format
endif

.PHONY: typecheck
typecheck: ## Strict type check (Python)
	$(MYPY)

.PHONY: dead-check
dead-check: ## Find unused code (Python: vulture, Frontend: knip)
	$(VULTURE) backend/app --min-confidence 80
ifdef FRONTEND_READY
	npx --no-install knip
endif

# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #

.PHONY: test
test: _artifacts_dir ## Run the full Briefed test suite and print a unified summary
	rm -f $(ARTIFACTS_DIR)/pytest.json $(ARTIFACTS_DIR)/pytest.xml \
	  $(ARTIFACTS_DIR)/vitest.json $(ARTIFACTS_DIR)/playwright.json \
	  $(ARTIFACTS_DIR)/promptfoo.json
ifdef EVAL
	@$(PROMPTFOO) --version >/dev/null
endif
	@set -o pipefail; \
	  $(PYTEST) -m "not e2e and not eval" \
	    --junitxml=$(ARTIFACTS_DIR)/pytest.xml \
	    --json-report --json-report-file=$(ARTIFACTS_DIR)/pytest.json || true
ifdef FRONTEND_READY
	@set -o pipefail; \
	  npm --workspace frontend run test -- \
	    --reporter=json --outputFile=../$(ARTIFACTS_DIR)/vitest.json || true
endif
ifdef PLAYWRIGHT
	PLAYWRIGHT=$(PLAYWRIGHT) npx playwright test \
	  --reporter=json > $(ARTIFACTS_DIR)/playwright.json || true
endif
ifdef EVAL
	$(PROMPTFOO) eval -c backend/eval/promptfoo.yaml \
	  --output $(ARTIFACTS_DIR)/promptfoo.json || true
endif
	$(PYTHON) backend/scripts/test_summary.py

.PHONY: e2e
e2e: ## Run Playwright e2e tests (sets PLAYWRIGHT=1)
	PLAYWRIGHT=1 $(MAKE) test

.PHONY: eval
eval: ## Run Promptfoo prompt evals (sets EVAL=1)
	EVAL=1 $(MAKE) test

# --------------------------------------------------------------------------- #
# Coverage                                                                    #
# --------------------------------------------------------------------------- #

.PHONY: coverage
coverage: _artifacts_dir ## Enforce the 80% line-coverage floor (+ listed 100% modules at 100%)
	$(PYTEST) -m "not e2e and not eval" \
	  --cov=backend/app \
	  --cov-report=term-missing \
	  --cov-report=xml:$(COV_BE_XML) \
	  --cov-fail-under=$(COVERAGE_FLOOR)
	$(PYTHON) backend/scripts/coverage_gate.py $(COV_BE_XML)
ifdef FRONTEND_READY
	npm --workspace frontend run test -- --coverage \
	  --coverage.thresholds.lines=$(COVERAGE_FLOOR) \
	  --coverage.thresholds.functions=$(COVERAGE_FLOOR) \
	  --coverage.thresholds.branches=70 \
	  --coverage.reporter=text --coverage.reporter=lcov
endif

# --------------------------------------------------------------------------- #
# Docs — OpenAPI export + TS client regen                                     #
# --------------------------------------------------------------------------- #

.PHONY: docs
docs: ## Regenerate packages/contracts/openapi.json + frontend TS client
	$(PYTHON) backend/scripts/export_openapi.py
ifdef FRONTEND_READY
	npm --workspace frontend run codegen
endif

.PHONY: link-check
link-check: ## Verify every relative link in README + docs/** resolves (Phase 9 release gate)
	$(PYTHON) backend/scripts/link_check.py

# --------------------------------------------------------------------------- #
# Database                                                                    #
# --------------------------------------------------------------------------- #

.PHONY: migrate
migrate: require-infisical ## Apply Alembic migrations (head) with Infisical secrets
	$(INFISICAL_RUN) $(ALEMBIC) -c backend/alembic.ini upgrade head

.PHONY: migrate-rev
migrate-rev: require-infisical ## alembic revision --autogenerate -m "<msg>"; pass MSG=...
	@test -n "$(MSG)" || (echo "usage: make migrate-rev MSG='your message'" && exit 1)
	$(INFISICAL_RUN) $(ALEMBIC) -c backend/alembic.ini revision --autogenerate -m "$(MSG)"

# --------------------------------------------------------------------------- #
# Security                                                                    #
# --------------------------------------------------------------------------- #

.PHONY: secrets-lint
secrets-lint: ## Scan repo for accidentally-committed secrets
	gitleaks detect --source . --report-format json --report-path $(ARTIFACTS_DIR)/gitleaks.json

.PHONY: audit
audit: ## pip-audit + bandit + npm audit (Phase 8 hardening)
	# --skip-editable so our own ``briefed-backend`` editable install isn't
	# reported as "not on PyPI". Without ``--strict`` pip-audit still fails
	# on real vulnerabilities but downgrades the skip to a warning.
	$(PIP_AUDIT) --skip-editable
	$(BANDIT) -c pyproject.toml -r backend/app
ifdef FRONTEND_READY
	npm --workspace frontend audit --audit-level=high
endif

# --------------------------------------------------------------------------- #
# Infra (Terraform)                                                           #
# --------------------------------------------------------------------------- #

.PHONY: tf-fmt
tf-fmt:
	terraform -chdir=infra/terraform fmt -recursive

.PHONY: tf-validate
tf-validate: ## terraform fmt -check + validate (dev + prod) — mirrors CI
	terraform -chdir=infra/terraform fmt -check -recursive
	cd infra/terraform/envs/dev  && terraform init -backend=false && terraform validate
	cd infra/terraform/envs/prod && terraform init -backend=false && terraform validate

.PHONY: deploy-dev
deploy-dev: ## Terraform apply the dev env (requires IMAGE_URI=...)
	@test -n "$(IMAGE_URI)" || (echo "usage: make deploy-dev IMAGE_URI=..." && exit 1)
	cd infra/terraform/envs/dev && terraform apply -var "image_uri=$(IMAGE_URI)"

# --------------------------------------------------------------------------- #
# CI parity                                                                   #
# --------------------------------------------------------------------------- #
#
# ``make ci`` runs the same gates GitHub Actions runs in .github/workflows/
# ci.yml so a clean run locally is a strong signal that PR checks will pass.
# Order mirrors the workflow: lint → test → coverage → docs drift → security
# → terraform.
#
# Skips that match CI:
#   - frontend-side steps short-circuit until package-lock.json exists
#     (FRONTEND_READY gate, same as the ``detect`` job).
#   - npm audit is gated on FRONTEND_READY (same as CI).
# Skips that DIFFER from CI (clearly called out below):
#   - gitleaks: requires the gitleaks binary on PATH; skipped if missing.
#   - trivy: same — skipped if the trivy binary is missing.
# Both run on every CI run, so install them locally if you want full parity:
#   ``brew install gitleaks trivy``.

.PHONY: ci
ci: ## Run every CI gate locally (lint, test, coverage, docs-drift, security, terraform)
	@echo "==> [1/6] lint"
	@$(MAKE) lint
	@echo "==> [2/6] test"
	@$(MAKE) test
	@echo "==> [3/6] coverage (floor=$(COVERAGE_FLOOR)%)"
	@$(MAKE) coverage
	@echo "==> [4/6] docs drift"
	@$(MAKE) docs
	@git diff --exit-code packages/contracts/openapi.json docs/ \
	  || (echo "docs drift detected — commit the regenerated artifacts" && exit 1)
	@$(MAKE) link-check
	@echo "==> [5/6] security audit"
	@$(MAKE) audit
	@if command -v gitleaks >/dev/null 2>&1; then \
	  $(MAKE) secrets-lint; \
	else \
	  echo "skip: gitleaks not installed (brew install gitleaks)"; \
	fi
	@if command -v trivy >/dev/null 2>&1; then \
	  trivy fs --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed \
	    --skip-dirs node_modules,.venv,build,dist,frontend/node_modules .; \
	else \
	  echo "skip: trivy not installed (brew install trivy)"; \
	fi
	@echo "==> [6/6] terraform fmt + validate"
	@$(MAKE) tf-validate
	@echo "==> CI parity OK"

# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #

.PHONY: _artifacts_dir
_artifacts_dir:
	@mkdir -p $(ARTIFACTS_DIR)
