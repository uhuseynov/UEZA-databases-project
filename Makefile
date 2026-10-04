# =============================================================================
# UZA Databases Project — Development Makefile
# =============================================================================

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --no-print-directory
.DEFAULT_GOAL := help


# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------

ifneq (,$(wildcard .env))
	include .env
	export
endif


# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------

APP_NAME := uza-databases-project

UV      := uv
DC      := docker compose
PYTEST  := $(UV) run pytest
ALEMBIC := $(UV) run alembic

VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
COMMIT  := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")

APP_PORT         ?= 8000
MARIADB_USER     ?= uza
MARIADB_PASSWORD ?= uza_password
MARIADB_DATABASE ?= uza_db


# -----------------------------------------------------------------------------
# Colors
# -----------------------------------------------------------------------------

BOLD   := \033[1m
RESET  := \033[0m
GREEN  := \033[32m
BLUE   := \033[34m
YELLOW := \033[33m
RED    := \033[31m
CYAN   := \033[36m


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

define confirm
	@printf "$(RED)⚠️  This is a destructive operation. Continue? [y/N] $(RESET)"; \
	read -r ans; \
	if [ "$$ans" != "y" ] && [ "$$ans" != "Y" ]; then \
		printf "$(YELLOW)Aborted.$(RESET)\n"; \
		exit 1; \
	fi
endef


define wait_for_healthy
	@cid=$$($(DC) ps -q $(1)); \
	if [ -z "$$cid" ]; then \
		printf "$(RED)❌ $(1) container not found.$(RESET)\n"; \
		exit 1; \
	fi; \
	attempt=0; \
	while [ $$attempt -lt 60 ]; do \
		status=$$(docker inspect \
			-f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
			$$cid 2>/dev/null || true); \
		if [ "$$status" = "healthy" ]; then \
			printf "$(GREEN)✅ $(1) is healthy.$(RESET)\n"; \
			exit 0; \
		fi; \
		if [ "$$status" = "unhealthy" ]; then \
			printf "$(RED)❌ $(1) is unhealthy.$(RESET)\n"; \
			$(DC) logs --tail=50 $(1); \
			exit 1; \
		fi; \
		sleep 1; \
		attempt=$$((attempt + 1)); \
	done; \
	printf "$(RED)❌ Timed out waiting for $(1).$(RESET)\n"; \
	$(DC) logs --tail=50 $(1); \
	exit 1
endef


# -----------------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------------

.PHONY: help
help: ## Shows this help message
	@printf "\n$(BOLD)UZA Databases Project$(RESET)\n"
	@printf "Usage: make $(CYAN)<command>$(RESET)\n"
	@awk 'BEGIN {FS = ":.*?## "} \
		/^##@/ { \
			printf "\n$(CYAN)%s$(RESET)\n", substr($$0, 5) \
		} \
		/^[a-zA-Z0-9_-]+:.*?## / { \
			printf "  $(GREEN)%-22s$(RESET) %s\n", $$1, $$2 \
		}' $(MAKEFILE_LIST)
	@printf "\n"


# =============================================================================
##@ Development
# =============================================================================

.PHONY: setup
setup: sync hooks ## Sets up locked dependencies and repository Git hooks
	@printf "$(GREEN)✅ Development environment ready.$(RESET)\n"


.PHONY: hooks
hooks: ## Configures repository Git hooks
	@printf "$(BLUE)🪝 Configuring Git hooks...$(RESET)\n"
	@./scripts/setup-hooks.sh


.PHONY: install
install: ## Installs all project dependencies
	@printf "$(BLUE)📦 Installing dependencies...$(RESET)\n"
	@$(UV) sync
	@printf "$(GREEN)✅ Dependencies installed.$(RESET)\n"


.PHONY: sync
sync: ## Synchronizes environment with uv.lock
	@printf "$(BLUE)📦 Synchronizing environment...$(RESET)\n"
	@$(UV) sync --locked
	@printf "$(GREEN)✅ Environment synchronized.$(RESET)\n"


.PHONY: lock
lock: ## Updates uv.lock
	@printf "$(BLUE)🔒 Updating dependency lockfile...$(RESET)\n"
	@$(UV) lock
	@printf "$(GREEN)✅ Lockfile updated.$(RESET)\n"


.PHONY: run
run: ## Runs FastAPI locally with hot reload
	@printf "$(BLUE)🚀 Starting FastAPI...$(RESET)\n"
	@$(UV) run uvicorn main:app \
		--app-dir src \
		--host 0.0.0.0 \
		--port $(APP_PORT) \
		--reload


# =============================================================================
##@ Testing
# =============================================================================

.PHONY: test
test: test-unit ## Runs the default test suite


.PHONY: test-unit
test-unit: ## Runs unit tests
	@printf "$(BLUE)🧪 Running unit tests...$(RESET)\n"
	@$(PYTEST) tests/unit
	@printf "$(GREEN)✅ Unit tests passed.$(RESET)\n"


.PHONY: test-integration
test-integration: ## Runs integration tests
	@printf "$(BLUE)🧪 Running integration tests...$(RESET)\n"
	@$(PYTEST) tests/integration
	@printf "$(GREEN)✅ Integration tests passed.$(RESET)\n"


.PHONY: test-all
test-all: ## Runs all tests
	@printf "$(BLUE)🧪 Running all tests...$(RESET)\n"
	@$(PYTEST)
	@printf "$(GREEN)✅ All tests passed.$(RESET)\n"


.PHONY: test-verbose
test-verbose: ## Runs all tests with verbose output
	@$(PYTEST) -vv


# =============================================================================
##@ Database
# =============================================================================

.PHONY: db-up
db-up: ## Starts only MariaDB and waits until healthy
	@printf "$(BLUE)🐬 Starting MariaDB...$(RESET)\n"
	@$(DC) up -d db
	@$(MAKE) wait-db


.PHONY: wait-db
wait-db: ## Waits until MariaDB is healthy
	@printf "$(YELLOW)⏳ Waiting for MariaDB...$(RESET)\n"
	$(call wait_for_healthy,db)


.PHONY: db-shell
db-shell: ## Opens a MariaDB shell
	@$(DC) exec db mariadb \
		-u$(MARIADB_USER) \
		-p$(MARIADB_PASSWORD) \
		$(MARIADB_DATABASE)


.PHONY: db-logs
db-logs: ## Tails MariaDB logs
	@$(DC) logs -f db


.PHONY: db-stop
db-stop: ## Stops MariaDB
	@$(DC) stop db


.PHONY: db-reset
db-reset: ## Recreates the MariaDB volume
	$(call confirm)
	@printf "$(RED)🗑️  Resetting MariaDB...$(RESET)\n"
	@$(DC) down
	@docker volume rm -f $${COMPOSE_PROJECT_NAME:-$$(basename "$$PWD")}_mariadb_data >/dev/null 2>&1 || true
	@$(DC) up -d db
	@$(MAKE) wait-db
	@printf "$(GREEN)✅ MariaDB reset complete.$(RESET)\n"


# =============================================================================
##@ Migrations
# =============================================================================

.PHONY: migrate
migrate: ## Applies all pending migrations locally
	@printf "$(BLUE)🗃️  Applying migrations...$(RESET)\n"
	@$(ALEMBIC) upgrade head
	@printf "$(GREEN)✅ Migrations applied.$(RESET)\n"


.PHONY: migration
migration: ## Creates migration: make migration m="message"
	@if [ -z "$(m)" ]; then \
		printf "$(RED)Usage: make migration m=\"migration message\"$(RESET)\n"; \
		exit 1; \
	fi
	@printf "$(BLUE)📝 Creating migration: $(m)$(RESET)\n"
	@$(ALEMBIC) revision --autogenerate -m "$(m)"
	@printf "$(GREEN)✅ Migration created.$(RESET)\n"


.PHONY: migration-empty
migration-empty: ## Creates empty migration: make migration-empty m="message"
	@if [ -z "$(m)" ]; then \
		printf "$(RED)Usage: make migration-empty m=\"migration message\"$(RESET)\n"; \
		exit 1; \
	fi
	@printf "$(BLUE)📝 Creating empty migration: $(m)$(RESET)\n"
	@$(ALEMBIC) revision -m "$(m)"
	@printf "$(GREEN)✅ Migration created.$(RESET)\n"


.PHONY: migration-down
migration-down: ## Reverts the latest migration
	@printf "$(YELLOW)↩️  Reverting latest migration...$(RESET)\n"
	@$(ALEMBIC) downgrade -1


.PHONY: migration-current
migration-current: ## Shows current database revision
	@$(ALEMBIC) current


.PHONY: migration-history
migration-history: ## Shows migration history
	@$(ALEMBIC) history


# =============================================================================
##@ Docker
# =============================================================================

.PHONY: up
up: ## Builds and starts the complete application stack
	@printf "$(BLUE)🐳 Starting application stack...$(RESET)\n"
	@$(DC) up -d --build
	@$(MAKE) wait-db
	@$(MAKE) wait-app
	@printf "$(GREEN)✅ Application is running at http://localhost:$(APP_PORT)$(RESET)\n"


.PHONY: wait-app
wait-app: ## Waits until FastAPI is healthy
	@printf "$(YELLOW)⏳ Waiting for FastAPI...$(RESET)\n"
	$(call wait_for_healthy,app)


.PHONY: down
down: ## Stops the application stack while preserving data
	@printf "$(YELLOW)🛑 Stopping application stack...$(RESET)\n"
	@$(DC) down
	@printf "$(GREEN)✅ Application stopped.$(RESET)\n"


.PHONY: down-volumes
down-volumes: ## Stops stack and deletes all project volumes
	$(call confirm)
	@printf "$(RED)🗑️  Removing containers and volumes...$(RESET)\n"
	@$(DC) down -v --remove-orphans
	@printf "$(GREEN)✅ Containers and volumes removed.$(RESET)\n"


.PHONY: restart
restart: ## Restarts the application stack
	@printf "$(YELLOW)🔄 Restarting application stack...$(RESET)\n"
	@$(DC) restart
	@$(MAKE) wait-db
	@$(MAKE) wait-app


.PHONY: build
build: ## Builds application Docker image
	@printf "$(BLUE)🔨 Building Docker image...$(RESET)\n"
	@$(DC) build app
	@printf "$(GREEN)✅ Docker image built.$(RESET)\n"


.PHONY: rebuild
rebuild: ## Rebuilds application image without cache
	@printf "$(BLUE)🔨 Rebuilding Docker image without cache...$(RESET)\n"
	@$(DC) build --no-cache app
	@printf "$(GREEN)✅ Docker image rebuilt.$(RESET)\n"


.PHONY: logs
logs: ## Tails logs from all services
	@$(DC) logs -f


.PHONY: app-logs
app-logs: ## Tails FastAPI logs
	@$(DC) logs -f app


.PHONY: ps
ps: ## Shows container status
	@$(DC) ps


.PHONY: shell
shell: ## Opens a shell inside the application container
	@$(DC) exec app /bin/bash


# =============================================================================
##@ CI
# =============================================================================

.PHONY: check
check: ## Runs local checks before committing
	@$(MAKE) test-unit


.PHONY: ci
ci: ## Runs CI checks using locked dependencies
	@printf "$(BLUE)🔍 Running CI checks...$(RESET)\n"
	@$(UV) sync --locked
	@$(PYTEST) tests/unit
	@printf "$(GREEN)✅ CI checks passed.$(RESET)\n"


# =============================================================================
##@ Utilities
# =============================================================================

.PHONY: version
version: ## Prints project version information
	@printf "Project: $(APP_NAME)\n"
	@printf "Version: $(VERSION)\n"
	@printf "Commit:  $(COMMIT)\n"


.PHONY: clean
clean: ## Removes generated Python/cache files
	@printf "$(YELLOW)🧹 Cleaning project...$(RESET)\n"
	@rm -rf \
		.pytest_cache \
		.ruff_cache \
		.mypy_cache \
		.coverage \
		htmlcov
	@find . \
		-type d \
		-name "__pycache__" \
		-prune \
		-exec rm -rf {} +
	@find . \
		-type f \
		-name "*.py[co]" \
		-delete
	@printf "$(GREEN)✅ Clean.$(RESET)\n"