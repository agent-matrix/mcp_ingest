# Makefile — helpers for dev/CI (Python 3.11 only)

PY ?= python3.11
VENV := .venv
PIP := $(VENV)/bin/pip
PYBIN := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
BLACK := $(VENV)/bin/black
MYPY := $(VENV)/bin/mypy
PYTEST := $(VENV)/bin/pytest

.PHONY: help setup install format lint typecheck test ci build clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' Makefile | sed 's/:.*##/\t-/' | sort

setup: ## Create local virtualenv (.venv)
	$(PY) -m venv $(VENV)
	$(PIP) install -U pip wheel

install: setup ## Install package + dev extras into .venv
	$(PIP) install -e ".[dev,harvester]"

format: ## Format code with black
	$(BLACK) mcp_ingest services tests || true

lint: ## Lint with ruff
	$(RUFF) check mcp_ingest services || true

typecheck: ## Static type checking with mypy
	$(MYPY) mcp_ingest services || true

test: ## Run tests (pytest)
	$(PYTEST) -q

ci: ## Lint + typecheck + tests (for CI)
	$(RUFF) check mcp_ingest services
	$(BLACK) --check mcp_ingest services
	$(MYPY) mcp_ingest services
	$(PYTEST) --maxfail=1 --disable-warnings -q --cov=mcp_ingest --cov-report=term-missing

build: ## Build sdist/wheel under dist/
	$(PYBIN) -m build

clean: ## Remove build artifacts & caches
	rm -rf dist build *.egg-info .pytest_cache .mypy_cache .ruff_cache

