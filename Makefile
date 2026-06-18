# ──────────────────────────────────────────────────────────────────────────────
# AutoLedger — Makefile
#
# Standard targets for local development and the Docker deployment.
# Run `make help` for a summary. The app stores data in ./data (gitignored);
# nothing here will touch or commit your real cost data.
# ──────────────────────────────────────────────────────────────────────────────

# Use bash with strict flags so a failing command fails the target loudly.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# Local virtualenv used by the non-Docker targets (setup/lint/fmt/test).
VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
PORT    ?= 5050

.DEFAULT_GOAL := help

.PHONY: help setup run run-local test lint fmt clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the local virtualenv and install deps + dev tools (ruff)
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt ruff
	@echo "Setup complete. Activate with: source $(VENV)/bin/activate"

run:  ## Build and start the app in Docker (http://localhost:$(PORT))
	docker compose up --build

run-local:  ## Run the Flask app directly on the host via the local venv
	DATA_DIR=./data $(PY) -m flask --app app run --port $(PORT) --debug

test:  ## Run the test suite (smoke check until a full suite lands — see ADR 0004)
	@echo "No automated test suite yet (tracked in docs/adr/0004-no-test-suite-yet.md)."
	@echo "Running an import smoke check instead:"
	$(PY) -c "import app; import routes.costs, routes.reports, routes.data; print('imports OK')"

lint:  ## Lint Python with ruff
	$(VENV)/bin/ruff check .

fmt:  ## Auto-format Python with ruff
	$(VENV)/bin/ruff format .

clean:  ## Remove caches and the local virtualenv (never touches ./data)
	rm -rf $(VENV) .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
