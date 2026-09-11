.DEFAULT_GOAL := help

UV ?= uv

#: Passed to `docker compose build`; a rebuild sets them to defeat the cache.
BUILD_FLAGS ?=

#: Where a release's image is published, and the version every package in the workspace carries.
IMAGE_REPO ?= ghcr.io/winterop-com/dirigent
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' packages/dirigent-cli/pyproject.toml)

#: The whole stack, object storage included: artifacts belong in a bucket.
COMPOSE ?= docker compose --project-directory . -f infra/compose.yaml

#: The stack plus the brokers examples/queues/ reads.
COMPOSE_QUEUES ?= $(COMPOSE) -f infra/compose.brokers.yaml

#: The stack plus the warehouse examples/sql/ reads.
COMPOSE_SQL ?= $(COMPOSE) -f infra/compose.sql.yaml

#: The stack plus somewhere to watch it: a collector, Prometheus, Tempo and Grafana.
COMPOSE_OTEL ?= $(COMPOSE) -f infra/compose.otel.yaml

#: The stack plus somewhere for the email and webhook channels to land.
COMPOSE_SINKS ?= $(COMPOSE) -f infra/compose.sinks.yaml

#: Every overlay at once, which is what "take it all away" has to name to reach every volume.
COMPOSE_ALL ?= $(COMPOSE) -f infra/compose.brokers.yaml -f infra/compose.sql.yaml -f infra/compose.otel.yaml -f infra/compose.sinks.yaml

.PHONY: help install lint static check gate e2e queues-up queues-down schemas dev dev-seeded ui ui-dev ui-fmt ui-lint ui-test ui-e2e ui-gate ui-static ui-wheel docker-build docker-rebuild docker-run docker-run-queues docker-run-sql docker-run-otel docker-run-sinks docker-run-all docker-clean test test-postgres test-s3 test-docker test-queues load coverage docs docs-blocks docs-settings docs-build clean

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Sync the workspace virtualenv with all dev dependencies
	$(UV) sync --all-packages

lint: ## Format and auto-fix (mutating)
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

static: ## Read-only gate without the tests: ruff, mypy, pyright, the UI type scale
	$(UV) run ruff format --check .
	$(UV) run ruff check .
	$(UV) run mypy packages
	$(UV) run pyright
	# Reads .ts/.tsx as text and needs no node, so it holds the type scale in every lane,
	# including the ones with no bun on them. `ui-lint` runs it too, for a UI contributor
	# whose one command should cover everything.
	$(UV) run python scripts/check_ui_classes.py

check: static ui-gate ## Read-only gate: the static one, the UI's, then the tests
	$(UV) run pytest

e2e: ## Only the end-to-end lane: dg dev, dg apply, dg run, dg runs, as subprocesses
	$(UV) run pytest -m e2e

test: ## Run the fast unit lane (SQLite)
	$(UV) run pytest

test-slowest: ## Run the fast lane and list the 25 slowest tests
	$(UV) run pytest --durations=25 --durations-min=0.1

test-postgres: ## Run the concurrency lane against a real PostgreSQL (needs Docker)
	$(UV) run pytest -m postgres

test-s3: ## Run the storage lane against a real S3-compatible server (needs Docker)
	$(UV) run pytest -m s3

test-docker: ## Run the docker.run lane against a real daemon (needs a Docker socket)
	$(UV) run pytest -m docker

#: The brokers the queue lane reads: `docker compose -f infra/compose.queues.yaml up -d`.
QUEUES_COMPOSE ?= docker compose -f infra/compose.queues.yaml

test-queues: ## Run the queue lane against real Kafka and RabbitMQ brokers (needs Docker)
	$(UV) run pytest -m queues

load: ## Measure the log path against a real PostgreSQL, printing load records (needs Docker)
	$(UV) run pytest -m load -s -q packages/dirigent-cli/tests/test_load.py

queues-up: ## Start the brokers the queue lane runs against
	$(QUEUES_COMPOSE) up -d --wait

queues-down: ## Stop those brokers and forget what they held
	$(QUEUES_COMPOSE) down -v

#: Where the seeded instance keeps its database, artifacts and secret key.
SEED_ROOT ?= .

#: Where the seeded instance listens.
SEED_HOST ?= 127.0.0.1
SEED_PORT ?= 3333

dev: ## Boot an empty instance for manual testing, wiping the state a previous one left
	$(UV) run dg dev --wipe-state --host $(SEED_HOST) --port $(SEED_PORT)

dev-seeded: ## Boot a seeded instance for manual testing; schedules land paused, some seeded runs fail on purpose
	$(UV) run python scripts/seed_dev.py --root $(SEED_ROOT) --host $(SEED_HOST) --port $(SEED_PORT) | $(UV) run dg format

FRONTEND ?= packages/dirigent-server/frontend

#: Empty when bun is not installed, which is what lets the Python-only lanes skip the UI gate.
BUN := $(shell command -v bun 2>/dev/null)

#: A frozen install touches no tracked file and is what makes a gate mean anything: the linter
#: has to be present before it can refuse.
FRONTEND_INSTALL = cd $(FRONTEND) && bun install --frozen-lockfile

ui: ## Build the web UI bundle into $(FRONTEND)/dist, which the server serves from a checkout
	$(FRONTEND_INSTALL) && bun run build

ui-dev: ## Serve the UI with hot reload, proxying the API to a running `dg dev`
	@echo "Start the API first: dg dev. Override its address with DIRIGENT_DEV_API."
	cd $(FRONTEND) && bun run dev

ui-fmt: ## Format the UI sources (mutating)
	$(FRONTEND_INSTALL) && bun run fmt

ui-lint: ## Read-only UI gate: the formatter, oxlint, the type checker, and the type scale
	$(FRONTEND_INSTALL) && bun run fmt:check
	cd $(FRONTEND) && bun run lint
	# tsc is the only thing that catches a type error: vite strips types without checking
	# them, and oxlint cannot see them either.
	cd $(FRONTEND) && bunx tsc -b
	$(UV) run python scripts/check_ui_classes.py

ui-test: ## Run the UI unit lane (vitest, node environment, no DOM)
	$(FRONTEND_INSTALL) && bun run test

ui-e2e: ## Drive a real `dg dev` in a browser. Needs `make ui` and `bunx playwright install chromium`
	cd $(FRONTEND) && bun run e2e

ui-shots: ## Photograph every screen in both palettes against a seeded instance, into $(FRONTEND)/shots
	cd $(FRONTEND) && bunx playwright test --config shots.config.ts

ui-gate: ## The UI's half of `make check`, skipped loudly where there is no bun to run it
	@if [ -z "$(BUN)" ]; then \
		echo "=== SKIPPING the web UI gate: bun is not on PATH."; \
		echo "=== Install bun (https://bun.sh) to lint, type-check and test the UI here."; \
	else \
		$(MAKE) ui-lint ui-test; \
	fi

ui-static: ui ## Put the built bundle where the server wheel packages it
	find packages/dirigent-server/src/dirigent_server/static -mindepth 1 -not -name .gitkeep -delete
	cp -R $(FRONTEND)/dist/. packages/dirigent-server/src/dirigent_server/static/

ui-wheel: ## Build the server wheel and prove it carries the UI bundle
	@test -f packages/dirigent-server/src/dirigent_server/static/index.html \
		|| { echo "Nothing to ship: run 'make ui' first."; exit 1; }
	rm -f dist/dirigent_server-*.whl
	$(UV) build --wheel --package dirigent-server --out-dir dist
	@unzip -l dist/dirigent_server-*.whl | grep -q 'dirigent_server/static/index.html' \
		|| { echo "The wheel carries no UI bundle: check the build backend's includes."; exit 1; }
	@echo "the wheel carries dirigent_server/static/"

docker-build: .env ## Build the image
	$(COMPOSE) build $(BUILD_FLAGS)

docker-push: export DIRIGENT_VERSION := $(VERSION)
docker-push: export DIRIGENT_REVISION := $(shell git rev-parse --short HEAD)
docker-push: docker-build ## Build with the version stamped in, prove the image starts and extends, and push it to GHCR
	docker tag dirigent:local $(IMAGE_REPO):$(VERSION)
	docker tag dirigent:local $(IMAGE_REPO):latest
	docker run --rm $(IMAGE_REPO):$(VERSION) version
	docker run --rm --entrypoint uv $(IMAGE_REPO):$(VERSION) --version
	docker push $(IMAGE_REPO):$(VERSION)
	docker push $(IMAGE_REPO):latest

docker-rebuild: .env docker-clean ## Start over: clean everything, then build from scratch
	$(MAKE) docker-build BUILD_FLAGS="--no-cache --pull"

docker-run: .env docker-build ## Run the stack in the foreground; ctrl-c stops it
	$(COMPOSE) up

docker-run-queues: .env docker-build ## Run the stack with the brokers examples/queues/ reads
	$(COMPOSE_QUEUES) up

docker-run-sql: .env docker-build ## Run the stack with the warehouse examples/sql/ reads
	$(COMPOSE_SQL) up

docker-run-otel: .env docker-build ## Run the stack with telemetry; Grafana on http://127.0.0.1:3300
	$(COMPOSE_OTEL) up

docker-run-sinks: .env docker-build ## Run the stack with the alert sinks; Mailpit on http://127.0.0.1:8025
	$(COMPOSE_SINKS) up

docker-run-all: .env docker-build ## Run the stack with every overlay: brokers, warehouse, telemetry, alert sinks
	$(COMPOSE_ALL) up

docker-clean: ## Remove the stack: containers, volumes, orphans, and the images built here
	$(COMPOSE_ALL) down --volumes --remove-orphans --rmi local

.env:
	@echo "No .env yet. Copy the example and set the one value it asks for:"
	@echo "  cp .env.example .env"
	@echo '  DIRIGENT_SECRET_KEY='$$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
	@exit 1

coverage: ## Run the test suite once, under coverage, and hold the gate
	$(UV) run coverage run -m pytest
	$(UV) run coverage report --fail-under=90

gate: static coverage ## What CI runs: the static gate, then the tests once, under coverage

export NO_MKDOCS_2_WARNING := 1

docs: ## Serve the documentation site locally on 127.0.0.1:3334
	$(UV) run mkdocs serve -a 127.0.0.1:3334

docs-blocks: ## Regenerate docs/blocks.md from the installed block catalog
	$(UV) run python -c "from pathlib import Path; \
from dirigent_core.blockdocs import PAGE_PATH, render; \
from dirigent_core.plugins import load_plugin_host; \
Path(PAGE_PATH).write_text(render(load_plugin_host().catalog()))"

docs-settings: ## Regenerate docs/settings.md from the settings model
	$(UV) run python -c "from pathlib import Path; \
from dirigent_core.configdocs import PAGE_PATH, render; \
Path(PAGE_PATH).write_text(render())"

schemas: ## Regenerate reports/schema-inventory.md from every pydantic model
	$(UV) run python scripts/schema_inventory.py

docs-build: ## Build the documentation site, failing on any warning
	$(UV) run mkdocs build --strict

clean: ## Remove build artifacts and tool caches
	rm -rf .ruff_cache .mypy_cache .pytest_cache htmlcov site .coverage coverage.xml
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.egg-info' -type d -prune -exec rm -rf {} +
