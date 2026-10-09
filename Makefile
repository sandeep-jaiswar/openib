# openib — one entry point for everything.
#
# The contract: a clean Ubuntu 24.04 box can do
#
#     git clone && make bootstrap && make daily
#
# and end up with a queryable warehouse, with no services, no credentials and
# no further input. `make check` is what CI runs.

SHELL := /bin/bash
.DEFAULT_GOAL := help

DATE ?= $(shell date -u +%F)
PROFILE ?= fixture
OB := PYTHONPATH=python python3 -m ob

.PHONY: help bootstrap daily daily-full run rebuild verify golden query ontology \
        sources test lint check bench clean reset

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

bootstrap: ## One-time machine setup (apt, rustup, uv). Idempotent.
	bash scripts/bootstrap-ubuntu.sh

daily: ## The hermetic daily run: fixture sources, then the determinism gate.
	$(OB) run --date $(DATE) --profile fixture --offline
	$(OB) verify --date $(DATE) --profile fixture

daily-full: ## The real daily run against live public sources (needs network).
	$(OB) run --date $(DATE) --profile full

run: ## Run one logical date: make run DATE=2026-10-09 PROFILE=full
	$(OB) run --date $(DATE) --profile $(PROFILE)

rebuild: ## Re-run every transform from the landing zone. Never re-fetches.
	$(OB) rebuild

verify: ## Golden-hash determinism check for DATE.
	$(OB) verify --date $(DATE) --profile $(PROFILE)

golden: ## Re-record the golden hashes. Review the diff before committing.
	$(OB) verify --date $(DATE) --profile $(PROFILE) --update

query: ## Point-in-time read: make query AS_OF=2025-06-30
	$(OB) query $(if $(AS_OF),--as-of $(AS_OF),)

ontology: ## Describe the ontology.
	$(OB) ontology

sources: ## List the source registry.
	$(OB) sources

test: ## Run the test suite (stdlib only, no network).
	python3 -m unittest discover -s tests -q

lint: ## Lint, if ruff is available.
	@if command -v ruff >/dev/null 2>&1; then ruff check python tests; \
	 else echo "ruff not installed; skipping (install with: uv tool install ruff)"; fi

check: test daily ## What CI runs: tests, then a full hermetic run and verify.

bench: ## Placeholder for the P1 benchmark gates (bench/README.md).
	@echo "benchmarks land in P1; see bench/README.md for the targets they gate on"

reset: ## Delete ./data. A clean slate for `make daily`.
	$(OB) reset

clean: reset ## Remove data and build artefacts.
	rm -rf .pytest_cache .ruff_cache target
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
