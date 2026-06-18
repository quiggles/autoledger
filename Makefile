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

# The app targets Python 3.12 (see Dockerfile) and uses 3.10+ syntax, so the
# test/lint targets run inside an ephemeral python:3.12-slim container with the
# source mounted. This matches production exactly and avoids depending on the
# host's Python version.
PYIMAGE := python:3.12-slim
DOCKER_PY = docker run --rm -v "$(CURDIR)":/app -w /app $(PYIMAGE) sh -c

setup:  ## Create the local virtualenv and install deps + dev tools
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	@echo "Setup complete. Activate with: source $(VENV)/bin/activate"
	@echo "Note: tests run on Python 3.12 via 'make test' (host Python may be older)."

run:  ## Build and start the app in Docker (http://localhost:$(PORT))
	docker compose up --build

run-local:  ## Run the Flask app directly on the host via the local venv
	DATA_DIR=./data $(PY) -m flask --app app run --port $(PORT) --debug

test:  ## Run the pytest suite on Python 3.12 in Docker (matches production)
	$(DOCKER_PY) "pip install -q -r requirements-dev.txt && python -m pytest"

lint:  ## Lint Python with ruff (Python 3.12 in Docker)
	$(DOCKER_PY) "pip install -q ruff==0.5.1 && ruff check ."

fmt:  ## Auto-format Python with ruff (Python 3.12 in Docker)
	$(DOCKER_PY) "pip install -q ruff==0.5.1 && ruff format ."

clean:  ## Remove caches and the local virtualenv (never touches ./data)
	rm -rf $(VENV) .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
