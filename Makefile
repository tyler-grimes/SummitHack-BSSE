.PHONY: check check-ts check-py test test-ts test-py lint lint-ts lint-py typecheck infra-up infra-down

# Run all checks (TypeScript + Python)
check: check-ts check-py

check-ts:
	npm run check

check-py: lint-py typecheck-py test-py

# TypeScript
test-ts:
	npm run test

lint-ts:
	npm run lint

typecheck-ts:
	npm run typecheck

# Python (run from each service dir)
test-py:
	cd services/forecasting && python -m pytest tests/ -v --cov=src --cov-report=term-missing
	cd services/optimization && python -m pytest tests/ -v --cov=src --cov-report=term-missing
	cd packages/data-pipeline && python -m pytest tests/ -v --cov=src --cov-report=term-missing

lint-py:
	ruff check services/ packages/data-pipeline/ simulation/
	ruff format --check services/ packages/data-pipeline/ simulation/

lint-py-fix:
	ruff check --fix services/ packages/data-pipeline/ simulation/
	ruff format services/ packages/data-pipeline/ simulation/

typecheck-py:
	mypy services/forecasting/src --config-file pyproject.toml
	mypy services/optimization/src --config-file pyproject.toml
	mypy packages/data-pipeline/src --config-file pyproject.toml

# Infrastructure
infra-up:
	docker compose up -d timescaledb kafka redis zookeeper
	@echo "Waiting for services..."
	@sleep 10

infra-down:
	docker compose down

infra-full:
	docker compose up -d

# E2E simulation
simulate:
	cd simulation && python -m pytest tests/test_e2e_simulation.py -v -s
