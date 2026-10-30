# Euron Open DataQuality: developer entry points. `make` lists every target.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE_DIR := deploy/compose
FLOCI       := docker compose --env-file $(COMPOSE_DIR)/.env -f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.floci.yaml
AWS_LOCAL   := docker compose --env-file $(COMPOSE_DIR)/.env -f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.aws.yaml
API         := cd apps/api &&
WEB         := cd apps/web &&
TF_IMAGE    := hashicorp/terraform:1.16.6
TF_ENVS     := local-floci aws-dev aws-prod
# Use a local terraform when installed, otherwise the pinned container.
TF          := $(shell command -v terraform >/dev/null 2>&1 && echo terraform || echo docker run --rm -v $(CURDIR)/infra:/infra -w /infra/terraform $(TF_IMAGE))
TF_ROOT     := $(shell command -v terraform >/dev/null 2>&1 && echo infra/terraform || echo /infra/terraform)
ENV         ?= aws-dev
# The demo password make env generated; e2e, qa and the seed use it.
DEMO_PW      = $(shell grep -s '^DQ_DEMO_PASSWORD=' $(COMPOSE_DIR)/.env | cut -d= -f2)
# The optional SQL Server source: make up MSSQL=1 (an amd64 image, emulated on Apple silicon).
ifeq ($(MSSQL),1)
export COMPOSE_PROFILES := mssql
endif

.PHONY: backup restore screenshots bench help env up up-aws down logs ps demo admin test test-integration test-matrix e2e qa \
        lint typecheck build openapi sanitize tf-fmt tf-validate tf-lint tf-security tf-aws-on-floci \
        aws-deploy aws-migrate aws-admin aws-plan clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\n"} /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ─── Local ───────────────────────────────────────────────────────────────────

env: ## Generate deploy/compose/.env with random local-only secrets
	@scripts/gen-local-env.sh

up: env ## Start everything on emulated AWS (Floci), provisioned by the same Terraform as production
	$(FLOCI) up -d --build --wait
	@echo ""
	@echo "  app        http://localhost:$${DQ_WEB_PORT:-4910}"
	@echo "  api        http://localhost:$${DQ_API_PORT:-4930}/docs"
	@echo "  mail       http://localhost:$${DQ_MAILPIT_PORT:-4925}   (alert emails land here)"
	@echo ""
	@echo "  Next: make demo   (users, projects, sources, datasets, checks, 30 days of history)"

up-aws: env ## Start the stack against real AWS resources (needs deploy/compose/.env.aws)
	@test -f $(COMPOSE_DIR)/.env.aws || { echo "copy $(COMPOSE_DIR)/.env.aws.example to .env.aws first"; exit 1; }
	$(AWS_LOCAL) up -d --build --wait

demo: ## Seed the demo: users, projects, sources, datasets, checks, alerts and 30 days of scans
	$(FLOCI) exec -T worker dataquality seed-demo
	@echo "  Sign in at http://localhost:$${DQ_WEB_PORT:-4910} with a demo account above, password $(DEMO_PW)"

backup: ## Back up the local stack: Postgres dump and the objects bucket, into backups/
	@scripts/backup.sh

restore: ## Restore a backup into the running stack (BACKUP=backups/<timestamp>)
	@test -n "$(BACKUP)" || { echo "usage: make restore BACKUP=backups/<timestamp>"; exit 1; }
	@scripts/restore.sh "$(BACKUP)"

down: ## Stop the stack and delete its data
	-$(FLOCI) down -v --remove-orphans
	-$(AWS_LOCAL) down -v --remove-orphans 2>/dev/null

admin: ## Create or reset an admin on the local stack (EMAIL=you@example.com; prompts for the password)
	@test -n "$(EMAIL)" || { echo "usage: make admin EMAIL=you@example.com"; exit 1; }
	$(FLOCI) exec api dataquality create-admin --email "$(EMAIL)"

logs: ## Tail logs (SERVICE=api|worker|web|floci|source-postgres|...)
	$(FLOCI) logs -f --tail 100 $(SERVICE)

ps: ## Show stack status
	$(FLOCI) ps

# ─── Quality ─────────────────────────────────────────────────────────────────

lint: ## Lint the API (ruff) and the web app (eslint)
	$(API) uv run ruff check src tests && uv run ruff format --check src tests
	@if [ -d apps/web ]; then $(WEB) pnpm lint; fi

typecheck: ## Typecheck the API (mypy --strict) and the web app (tsc)
	$(API) uv run mypy --strict src
	@if [ -d apps/web ]; then $(WEB) pnpm typecheck; fi

test: ## Unit tests: API (pytest) and web (vitest). No database, no network
	$(API) uv run pytest tests/unit -q
	@if [ -d apps/web ]; then $(WEB) pnpm test; fi

test-integration: ## API integration tests against real Postgres, Redis, Floci and the source databases (started if needed)
	@scripts/test-db.sh
	$(API) uv run pytest tests/unit tests/integration -q --cov=dataquality --cov-report=term-missing:skip-covered --cov-fail-under=85

bench: ## Scale benchmark: profile and check a 1,000,000 row PostgreSQL table (make up first)
	$(API) uv run python -m tests.bench.bench_million

test-matrix: ## Integration tests under every key and storage backend (local and Floci KMS, local and Floci S3)
	@scripts/test-matrix.sh

e2e: ## Browser end-to-end tests (Playwright) against the running stack (make up && make demo)
	cd e2e && pnpm install --frozen-lockfile && pnpm exec playwright install chromium && E2E_PASSWORD='$(DEMO_PW)' pnpm test

qa: ## Browser QA sweep (Puppeteer): every page, light and dark, desktop and phone
	cd scripts/qa && pnpm install --frozen-lockfile && QA_PASSWORD='$(DEMO_PW)' node qa.mjs

screenshots: ## Curated screenshots (docs/assets/screenshots) and the tour GIF, from the seeded stack
	cd scripts/qa && pnpm install --frozen-lockfile && QA_PASSWORD='$(DEMO_PW)' node screenshots.mjs && ./make-tour.sh

build: ## Build the container images
	$(FLOCI) build

openapi: ## Regenerate docs/api/openapi.yaml from the FastAPI app
	@mkdir -p docs/api
	$(API) uv run dataquality openapi > ../../docs/api/openapi.yaml

sanitize: ## Scan committable files for credentials, cloud identifiers and em/en dashes
	@scripts/check-sanitization.sh

# ─── Terraform ───────────────────────────────────────────────────────────────

tf-fmt: ## Format all Terraform
	$(TF) fmt -recursive $(TF_ROOT)

tf-validate: ## terraform validate every environment (no backend, no credentials)
	@for env in $(TF_ENVS); do \
	  echo "== $$env"; \
	  $(TF) -chdir=$(TF_ROOT)/envs/$$env init -backend=false -input=false -no-color >/dev/null && \
	  $(TF) -chdir=$(TF_ROOT)/envs/$$env validate -no-color || exit 1; \
	done

tf-lint: ## tflint every module and environment (plugins cached in a docker volume)
	docker run --rm -v $(CURDIR)/infra:/data -v dataquality-tflint:/plugins -e TFLINT_PLUGIN_DIR=/plugins -w /data/terraform ghcr.io/terraform-linters/tflint:v0.64.0 --init
	docker run --rm -v $(CURDIR)/infra:/data -v dataquality-tflint:/plugins -e TFLINT_PLUGIN_DIR=/plugins -w /data/terraform ghcr.io/terraform-linters/tflint:v0.64.0 --recursive --format compact

tf-security: ## checkov policy scan of the Terraform
	docker run --rm -v $(CURDIR)/infra:/infra -w /infra/terraform bridgecrew/checkov:3.3.30 -d . --framework terraform --quiet --compact --config-file .checkov.yaml

tf-aws-on-floci: ## Plan, apply, re-plan and destroy the full aws-dev environment against a throwaway Floci
	@scripts/tf-aws-on-floci.sh

aws-deploy: ## One shot: registries, images, infrastructure, migrations, rollout (ENV=aws-dev|aws-prod TAG=...)
	@test -n "$(TAG)" || { echo "usage: make aws-deploy ENV=aws-dev TAG=0.1.0"; exit 1; }
	@scripts/aws-deploy.sh $(ENV) $(TAG)

aws-migrate: ## Run database migrations as a one-off ECS task (ENV=...)
	@scripts/aws-run-task.sh $(ENV) migrate

aws-admin: ## Create the first admin as a one-off ECS task (ENV=... EMAIL=...; DATAQUALITY_ADMIN_PASSWORD in your env)
	@test -n "$(EMAIL)" || { echo "usage: DATAQUALITY_ADMIN_PASSWORD=... make aws-admin ENV=aws-dev EMAIL=you@example.com"; exit 1; }
	@test -n "$$DATAQUALITY_ADMIN_PASSWORD" || { echo "set DATAQUALITY_ADMIN_PASSWORD (at least 10 characters, upper and lower case and a digit)"; exit 1; }
	@scripts/aws-run-task.sh $(ENV) create-admin --email "$(EMAIL)"

aws-plan: ## terraform plan for ENV (aws-dev | aws-prod); needs terraform.tfvars and AWS credentials
	cd infra/terraform/envs/$(ENV) && terraform init -input=false && terraform plan

clean: ## Remove build output and caches
	rm -rf apps/web/.next apps/api/.pytest_cache apps/api/.mypy_cache apps/api/.ruff_cache apps/api/.coverage e2e/test-results e2e/playwright-report scripts/qa/output
