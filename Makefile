# Makefile — helpers for dev/CI/docs (Python 3.11 only)
# -----------------------------------------------------------------------------
SHELL := /bin/bash
PY ?= python3.11
VENV := .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
PYBIN := $(BIN)/python
RUFF := $(BIN)/ruff
BLACK := $(BIN)/black
MYPY := $(BIN)/mypy
PYTEST := $(BIN)/pytest
MKDOCS := $(BIN)/mkdocs
UVICORN := $(BIN)/uvicorn

export PYTHONDONTWRITEBYTECODE=1

.PHONY: help setup install install-dev install-docs format lint typecheck test ci build clean clean-all \
	docs-setup docs-serve docs-build docs-publish docs-open \
	run-harvester harvest-mcp-servers tools

help: ## Show this help
	@echo "Targets:"; \
	grep -E '^[a-zA-Z0-9_-]+:.*?## ' Makefile | sed 's/:.*##/\t-/' | sort

# -----------------------------------------------------------------------------
# Setup & install
# -----------------------------------------------------------------------------
setup: ## Create local virtualenv (.venv)
	@test -d $(VENV) || $(PY) -m venv $(VENV)
	$(PIP) install -U pip wheel

install: setup ## Install package + dev extras into .venv
	$(PIP) install -e ".[dev,harvester]"

install-dev: install docs-setup ## Install everything needed for local dev (incl. docs)

# -----------------------------------------------------------------------------
# Code quality
# -----------------------------------------------------------------------------
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
	@echo "✔ CI checks passed"

build: ## Build sdist/wheel under dist/
	$(PYBIN) -m build

clean: ## Remove build artifacts & caches
	rm -rf dist build *.egg-info .pytest_cache .mypy_cache .ruff_cache site

clean-all: clean ## Clean venv too (DANGEROUS)
	rm -rf $(VENV)

# -----------------------------------------------------------------------------
# Docs (MkDocs + Material)
# -----------------------------------------------------------------------------
docs-setup: ## Install MkDocs and plugins into .venv
	$(PIP) install mkdocs mkdocs-material mkdocs-mermaid2-plugin

docs-serve: ## Serve docs locally at http://127.0.0.1:8001
	$(MKDOCS) serve -a 0.0.0.0:8001

docs-build: ## Build static docs into ./site (strict mode)
	$(MKDOCS) build --strict

docs-publish: ## Publish docs to GitHub Pages (requires git repo)
	$(MKDOCS) gh-deploy --force

docs-open: ## Open the built docs in your browser (after docs-build)
	@if command -v xdg-open >/dev/null; then xdg-open site/index.html; \
	elif command -v open >/dev/null; then open site/index.html; \
	else echo "Open site/index.html manually"; fi

# -----------------------------------------------------------------------------
# Runners / Examples
# -----------------------------------------------------------------------------
run-harvester: ## Run the Harvester API locally on :8088
	$(UVICORN) services.harvester.app:app --reload --port 8088

harvest-mcp-servers: ## Demo: harvest the MCP servers monorepo ZIP to ./dist/servers
	$(BIN)/mcp-ingest harvest-repo \
	  https://github.com/modelcontextprotocol/servers/archive/refs/heads/main.zip \
	  --out dist/servers

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
tools: ## Print tool versions in the current venv
	@echo "Python:" $$($(PYBIN) --version)
	@echo "pip:" $$($(PIP) --version)
	@echo "ruff:" $$($(RUFF) --version 2>/dev/null || echo 'missing')
	@echo "black:" $$($(BLACK) --version 2>/dev/null || echo 'missing')
	@echo "mypy:" $$($(MYPY) --version 2>/dev/null || echo 'missing')
	@echo "pytest:" $$($(PYTEST) --version 2>/dev/null || echo 'missing')
	@echo "mkdocs:" $$($(MKDOCS) --version 2>/dev/null || echo 'missing')
