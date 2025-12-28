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

# Only operate on directories that exist (avoids errors when tests/ is missing)
SRC_DIRS := mcp_ingest services examples tests
EXISTING_DIRS := $(shell for d in $(SRC_DIRS); do [ -d $$d ] && printf "%s " $$d; done)

.PHONY: help setup install install-dev install-docs format lint typecheck test ci build clean clean-all \
	docs-setup docs-serve docs-build docs-publish docs-open \
	run-harvester harvest-mcp-servers tools \
	catalog-example catalog-test catalog-help

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
	@dirs="$(EXISTING_DIRS)"; \
	if [ -z "$$dirs" ]; then echo "No source directories to format."; else \
		$(BLACK) $$dirs; fi

lint: ## Lint with ruff
	@dirs="$(EXISTING_DIRS)"; \
	if [ -z "$$dirs" ]; then echo "No source directories to lint."; else \
		$(RUFF) check $$dirs; fi

typecheck: ## Static type checking with mypy
	@dirs="$(EXISTING_DIRS)"; \
	if [ -z "$$dirs" ]; then echo "No source directories to typecheck."; else \
		$(MYPY) $$dirs; fi

test: ## Run tests with verbosity (pytest -sv)
	@if [ -d tests ]; then \
		PYTHONWARNINGS=default PYTHONLOGLEVEL=DEBUG $(PYTEST) -sv; \
	else \
		echo "No tests/ folder; skipping pytest."; \
	fi

ci: ## Lint + format check + tests (for CI)
	@dirs="$(EXISTING_DIRS)"; \
	if [ -n "$$dirs" ]; then $(RUFF) check $$dirs; else echo "No source dirs for ruff"; fi
	@dirs="$(EXISTING_DIRS)"; \
	if [ -n "$$dirs" ]; then $(BLACK) --check $$dirs; else echo "No source dirs for black"; fi
	@if [ -d tests ]; then $(PYTEST) --maxfail=1 --disable-warnings -q --cov=mcp_ingest --cov-report=term-missing; \
	else echo "No tests/ folder; skipping pytest."; fi
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

#harvest-mcp-servers: ## Demo: harvest the MCP servers monorepo ZIP to ./dist/servers
# 	$(BIN)/mcp-ingest harvest-repo \
# 		https://github.com/modelcontextprotocol/servers/archive/refs/heads/main.zip \
# 		--out dist/servers
harvest-mcp-servers: ## Harvest README-linked servers to ./dist/servers
	$(BIN)/mcp-ingest harvest-source https://github.com/modelcontextprotocol/servers --out dist/servers --yes


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

# -----------------------------------------------------------------------------
# Catalog Automation Examples (for agent-matrix/catalog)
# -----------------------------------------------------------------------------
catalog-help: ## Show catalog automation help
	@echo "===================================================================="
	@echo "Catalog Automation Examples"
	@echo "===================================================================="
	@echo ""
	@echo "These commands demonstrate the catalog automation reference"
	@echo "implementation in examples/catalog-automation/"
	@echo ""
	@echo "Commands:"
	@echo "  make catalog-example   Copy automation files to ../catalog"
	@echo "  make catalog-test      Test automation locally (safe)"
	@echo "  make catalog-help      This help message"
	@echo ""
	@echo "Documentation:"
	@echo "  See: examples/catalog-automation/README.md"
	@echo "  See: docs/catalog-automation.md"
	@echo ""
	@echo "After copying to your catalog repo, use:"
	@echo "  cd ../catalog"
	@echo "  make sync         # Full sync (harvest → dedupe → validate)"
	@echo "  make help         # See all catalog commands"
	@echo ""

catalog-example: ## Copy catalog automation to ../catalog directory
	@if [ ! -d "../catalog" ]; then \
		echo "❌ Directory ../catalog not found"; \
		echo "   Clone it first: git clone https://github.com/agent-matrix/catalog ../catalog"; \
		exit 1; \
	fi
	@echo "📦 Copying catalog automation files to ../catalog..."
	@cp -r examples/catalog-automation/.github/workflows/*.yml ../catalog/.github/workflows/ 2>/dev/null || \
		(mkdir -p ../catalog/.github/workflows && cp examples/catalog-automation/.github/workflows/*.yml ../catalog/.github/workflows/)
	@mkdir -p ../catalog/scripts && cp examples/catalog-automation/scripts/*.py ../catalog/scripts/
	@mkdir -p ../catalog/schema && cp examples/catalog-automation/schema/*.json ../catalog/schema/
	@cp examples/catalog-automation/Makefile ../catalog/ 2>/dev/null || echo "Makefile exists, skipping"
	@cp examples/catalog-automation/test-workflow-locally.sh ../catalog/ 2>/dev/null || true
	@chmod +x ../catalog/scripts/*.py ../catalog/test-workflow-locally.sh 2>/dev/null || true
	@echo "✅ Files copied to ../catalog"
	@echo ""
	@echo "Next steps:"
	@echo "  cd ../catalog"
	@echo "  make install    # Install dependencies"
	@echo "  make help       # See all commands"
	@echo "  make sync       # Run a sync"
	@echo ""

catalog-test: ## Test catalog automation locally (requires ../catalog)
	@if [ ! -d "../catalog" ]; then \
		echo "❌ Directory ../catalog not found"; \
		echo "   Clone it first: git clone https://github.com/agent-matrix/catalog ../catalog"; \
		exit 1; \
	fi
	@echo "🧪 Testing catalog automation..."
	@cd ../catalog && make test-sync 2>/dev/null || \
		echo "❌ Catalog automation not set up. Run 'make catalog-example' first."
