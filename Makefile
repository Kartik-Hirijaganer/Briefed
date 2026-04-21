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

export PYTHONPATH := backend:$(PYTHONPATH)

# Frontend is scaffolded in Phase 6. Until ``frontend/package-lock.json``
# exists, frontend-side targets are gracefully skipped so Phase 0 CI can
# go green. Phase 6's first commit lands the lock file and flips the gate.
FRONTEND_READY := $(shell test -f frontend/package-lock.json && echo 1)

.PHONY: help
help:
	@awk 'BEGIN{FS=":.*##"; printf "\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# --------------------------------------------------------------------------- #
# Bootstrap + dev loop                                                        #
# --------------------------------------------------------------------------- #

.PHONY: bootstrap
bootstrap: ## Install Python + Node deps and start docker-compose services
	pip install -e ".[dev]"
ifneq (,$(wildcard frontend/package.json))
	npm --prefix frontend install
endif
	docker compose up -d

.PHONY: dev
dev: ## Run backend + frontend with hot-reload (requires docker-compose services)
	docker compose up -d postgres
ifdef FRONTEND_READY
	( uvicorn app.main:app --app-dir backend --reload & \
	  npm --prefix frontend run dev & \
	  wait )
else
	uvicorn app.main:app --app-dir backend --reload
endif

.PHONY: clean
clean: ## Remove build + test + coverage artifacts
	rm -rf $(ARTIFACTS_DIR) .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
	rm -rf frontend/coverage frontend/dist frontend/node_modules/.vite

# --------------------------------------------------------------------------- #
# Lint / format / type-check                                                  #
# --------------------------------------------------------------------------- #

.PHONY: lint
lint: ## Run all linters (Python + Frontend)
	ruff check .
	ruff format --check .
	mypy
ifdef FRONTEND_READY
	npm --prefix frontend run lint
endif

.PHONY: format
format: ## Apply formatters
	ruff format .
	ruff check --fix .
ifdef FRONTEND_READY
	npm --prefix frontend run format
endif

.PHONY: typecheck
typecheck: ## Strict type check (Python)
	mypy

# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #

.PHONY: test
test: _artifacts_dir ## Run the full Briefed test suite and print a unified summary
	rm -f $(ARTIFACTS_DIR)/pytest.json $(ARTIFACTS_DIR)/pytest.xml \
	  $(ARTIFACTS_DIR)/vitest.json $(ARTIFACTS_DIR)/playwright.json \
	  $(ARTIFACTS_DIR)/promptfoo.json
ifdef EVAL
	@command -v promptfoo >/dev/null || \
	  (echo "promptfoo is required for make eval; install it before running evals." && exit 127)
endif
	@set -o pipefail; \
	  pytest -m "not e2e and not eval" \
	    --junitxml=$(ARTIFACTS_DIR)/pytest.xml \
	    --json-report --json-report-file=$(ARTIFACTS_DIR)/pytest.json || true
ifdef FRONTEND_READY
	@set -o pipefail; \
	  npm --prefix frontend run test -- \
	    --reporter=json --outputFile=$(ARTIFACTS_DIR)/vitest.json || true
endif
ifdef PLAYWRIGHT
	PLAYWRIGHT=$(PLAYWRIGHT) npx playwright test \
	  --reporter=json > $(ARTIFACTS_DIR)/playwright.json || true
endif
ifdef EVAL
	promptfoo eval -c backend/eval/promptfoo.yaml \
	  --output $(ARTIFACTS_DIR)/promptfoo.json || true
endif
	python backend/scripts/test_summary.py

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
	pytest -m "not e2e and not eval" \
	  --cov=backend/app \
	  --cov-report=term-missing \
	  --cov-report=xml:$(COV_BE_XML) \
	  --cov-fail-under=$(COVERAGE_FLOOR)
	python backend/scripts/coverage_gate.py $(COV_BE_XML)
ifdef FRONTEND_READY
	npm --prefix frontend run test -- --coverage \
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
	python backend/scripts/export_openapi.py
ifdef FRONTEND_READY
	npx --prefix frontend openapi-typescript \
	  packages/contracts/openapi.json \
	  -o frontend/src/api/schema.d.ts
endif

# --------------------------------------------------------------------------- #
# Database                                                                    #
# --------------------------------------------------------------------------- #

.PHONY: migrate
migrate: ## Apply Alembic migrations (head)
	alembic -c backend/alembic.ini upgrade head

.PHONY: migrate-rev
migrate-rev: ## alembic revision --autogenerate -m "<msg>"; pass MSG=...
	@test -n "$(MSG)" || (echo "usage: make migrate-rev MSG='your message'" && exit 1)
	alembic -c backend/alembic.ini revision --autogenerate -m "$(MSG)"

# --------------------------------------------------------------------------- #
# Security                                                                    #
# --------------------------------------------------------------------------- #

.PHONY: secrets-lint
secrets-lint: ## Scan repo for accidentally-committed secrets
	gitleaks detect --source . --report-format json --report-path $(ARTIFACTS_DIR)/gitleaks.json

.PHONY: audit
audit: ## pip-audit + npm audit
	# --skip-editable so our own ``briefed-backend`` editable install isn't
	# reported as "not on PyPI". Without ``--strict`` pip-audit still fails
	# on real vulnerabilities but downgrades the skip to a warning.
	pip-audit --skip-editable
ifdef FRONTEND_READY
	npm --prefix frontend audit --audit-level=high
endif

# --------------------------------------------------------------------------- #
# Infra (Terraform)                                                           #
# --------------------------------------------------------------------------- #

.PHONY: tf-fmt
tf-fmt:
	terraform -chdir=infra/terraform fmt -recursive

.PHONY: tf-validate
tf-validate:
	cd infra/terraform/envs/dev && terraform init -backend=false && terraform validate

.PHONY: deploy-dev
deploy-dev: ## Terraform apply the dev env (requires IMAGE_URI=...)
	@test -n "$(IMAGE_URI)" || (echo "usage: make deploy-dev IMAGE_URI=..." && exit 1)
	cd infra/terraform/envs/dev && terraform apply -var "image_uri=$(IMAGE_URI)"

# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #

.PHONY: _artifacts_dir
_artifacts_dir:
	@mkdir -p $(ARTIFACTS_DIR)
