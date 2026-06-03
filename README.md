# Seed Server

FastAPI AI orchestration backend with a React Saga Console for building, sandboxing, and inspecting workflow runs.

This repository is prepared as a portfolio demo. It is not presented as a perfect production product; it is a compact showcase of backend architecture, workflow orchestration, runtime safety, and an operator-facing UI.

## What To Review

- Saga workflow runtime with typed modules, flow graphs, sandbox runs, run history, and artifacts.
- React Saga Console with gallery, canvas, modules, providers, and run inspection.
- Deterministic stub mode so reviewers can run the demo without Gemini, OpenAI, Redis, or PostgreSQL credentials.
- NeoEats/domain blocks and broader API surface showing how a vertical product can be wired into the same runtime.
- Security posture: scoped auth, public-mode guards, API key hashing, audit events, and test-auth isolation.

## Quick Demo

Prerequisites:

- Python 3.11+
- Node.js 18+

Install backend dependencies once:

```bash
python -m pip install -e ".[dev]"
```

Start the portfolio demo:

```bash
python scripts/run_portfolio_demo.py
```

Or, if you have `make`:

```bash
make demo
```

The launcher starts the FastAPI backend and Saga Console, chooses free local ports, seeds a demo flow, and opens the UI.

Default credentials:

```text
Username: L0g1n
Password: P@SSW0RD
```

## Demo Walkthrough

1. Open Saga Console.
2. Go to `Gallery` and open `market_scan_default`.
3. Inspect the flow on `Canvas`.
4. Return to `Gallery` and run `Sandbox`.
5. Go to `Modules` and run `general_assistant` in stub mode.
6. Open `Runs` and inspect the timeline/result.

This path demonstrates the core story: gallery flow -> compiled graph -> module interaction -> sandbox execution -> run observability.

## Smoke Test

Run a non-interactive demo check:

```bash
python scripts/run_portfolio_demo.py --smoke-test --no-open
```

This starts local services, verifies `/v1/me`, seeds the demo flow, sandboxes it, runs a module in stub mode, checks the frontend, and exits.

## Manual Local Development

Backend:

```bash
SEED_ENV=test \
SEED_TEST_AUTH_MODE=1 \
SEED_DEV_CORS=1 \
SEED_ENABLE_STUB=1 \
SEED_DEFAULT_PROVIDER_FAST=stub \
SEED_DEFAULT_PROVIDER_BATCH=stub \
SEED_METRICS_ENABLED=0 \
SEED_ADMIN_KEY=portfolio_demo_admin \
SEED_API_KEY_PEPPER=portfolio_demo_pepper \
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd saga-console
npm install
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

On Windows PowerShell, set env vars with `$env:NAME = "value"` before starting the command.

## Docker Development

For a fuller local stack:

```bash
docker compose -f docker-compose.dev.yml up --build
```

The portfolio demo does not require Docker. Docker remains useful for testing the larger stack with Redis/PostgreSQL.

## Project Structure

```text
app/
  api/                 FastAPI routers, including console facade
  core/                auth, blocks, saga runtime, NeoEats blocks
  infrastructure/      db, cors, middleware, monitoring
  services/            LLM/service abstractions and registries
modules/               YAML module definitions
saga-console/          React + Vite operator console
scripts/               demo, seeding, verification helpers
tests/                 unit and integration coverage
docs/                  portfolio brief and deeper notes
```

## Useful Commands

```bash
python scripts/run_portfolio_demo.py --smoke-test --no-open
python -m pytest -q tests/unit/test_console_runtime_api.py
python -m pytest -q tests/unit/test_module_registry.py tests/unit/test_modes_api.py
cd saga-console && npm run build
```

## Portfolio Notes

Before publishing, use [docs/PUBLISH_CHECKLIST.md](docs/PUBLISH_CHECKLIST.md).

Suggested GitHub description:

```text
FastAPI AI orchestration backend with saga workflows, module runtime APIs, NeoEats domain automation, and a React visual Saga Console.
```

Suggested topics:

```text
fastapi, ai-orchestration, workflow-engine, saga-pattern, react-flow, typescript, llm, portfolio-project
```

Known demo boundaries:

- The demo defaults to deterministic stub providers, not real paid LLM calls.
- Some deeper production surfaces are included to show engineering range, but the reviewer path should focus on Saga Console and the console runtime API.
- The worktree may contain historical/generated artifacts during local development; publish from a cleaned branch or release archive.
