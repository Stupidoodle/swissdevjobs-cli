.DEFAULT_GOAL := help
.PHONY: help install lint lint-fix format typecheck arch test test-unit test-live check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies
	uv sync

lint: ## Run ruff
	uv run ruff check src/ tests/

lint-fix: ## Run ruff with auto-fix
	uv run ruff check --fix src/ tests/

format: ## Format, then fix lints
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

typecheck: ## Run ty
	uv run ty check src/

arch: ## Check the layering contracts (import-linter; needs Python >= 3.10)
	uv run lint-imports

test: ## Offline test suite with coverage
	uv run pytest --cov --cov-report=term-missing

test-unit: ## Offline tests only, no coverage gate
	uv run pytest -q --no-cov

test-live: ## Read-only smoke against the real boards; needs SDJ_LIVE=1
	SDJ_LIVE=1 uv run pytest -m live

check: lint typecheck arch test ## The full local gate

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .coverage .coverage.* htmlcov dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
