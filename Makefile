PYTHON ?= python
ADMIN_KEY ?= dev-only-change-before-deploy

.PHONY: run setup dev dev-down dev-logs dev-detach dev-seed demo demo-smoke quality quality-integration quality-experimental test clean lint typecheck security format coverage migrate docker-build console console-build

# Portfolio demo: backend + Saga Console, stub LLM, no Docker and no real API keys.
demo:
	$(PYTHON) scripts/run_portfolio_demo.py

demo-smoke:
	$(PYTHON) scripts/run_portfolio_demo.py --smoke-test --no-open

quality:
	$(PYTHON) scripts/run_quality_gate.py portfolio

quality-integration:
	$(PYTHON) scripts/run_quality_gate.py integration

quality-experimental:
	$(PYTHON) scripts/run_quality_gate.py experimental

# Start minimal Docker dev stack (postgres + redis + api with stub LLM).
dev:
	docker compose -f docker-compose.dev.yml up --build

dev-down:
	docker compose -f docker-compose.dev.yml down

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f api

dev-detach:
	docker compose -f docker-compose.dev.yml up --build -d

dev-seed:
	$(PYTHON) scripts/seed_demo.py --key $(ADMIN_KEY)

run:
	$(PYTHON) -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --reload

setup:
	$(PYTHON) -m pip install -e ".[dev]"
	@echo "Done. Run 'make demo' for the portfolio demo."

console:
	cd saga-console && npm install && npm run dev

console-build:
	cd saga-console && npm install && npm run build

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m flake8 app/ --max-line-length=120
	$(PYTHON) -m pylint app/ --disable=C,R --max-line-length=120

typecheck:
	$(PYTHON) -m mypy app/ --ignore-missing-imports

security:
	$(PYTHON) -m bandit -r app/ -q
	$(PYTHON) -m pip_audit

format:
	$(PYTHON) -m black app/ tests/
	$(PYTHON) -m isort --profile=black app/ tests/

coverage:
	$(PYTHON) -m pytest --cov=app --cov-report=html --cov-report=term-missing

migrate:
	$(PYTHON) -m alembic upgrade head

docker-build:
	docker compose build

clean:
	$(PYTHON) -c "import shutil, pathlib; paths=['.pytest_cache','__pycache__','htmlcov','.coverage','.demo']; [shutil.rmtree(p, ignore_errors=True) for p in paths]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
