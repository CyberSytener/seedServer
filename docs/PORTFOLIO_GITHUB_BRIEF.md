# Portfolio GitHub Brief

## Repository Positioning

Seed Server v5 is a backend portfolio project centered on AI workflow
orchestration. The strongest framing is:

> A FastAPI runtime for safe AI workflow execution, with saga-based flow
> orchestration, module and run governance, NeoEats as a concrete domain
> vertical, and a React operator console for visual workflow inspection.

This should be presented as a platform/backend systems project rather than a
single food app. NeoEats is valuable because it proves the runtime can support a
real domain: inventory, recipe generation, receipt intake, cooking state,
profile memory, and order sagas.

## Suggested GitHub Description

```text
FastAPI AI orchestration backend with saga workflows, module/flow runtime APIs,
NeoEats domain automation, agent sessions, and a React visual Saga Console.
```

Shorter alternative:

```text
AI workflow orchestration backend with FastAPI, sagas, Redis, PostgreSQL,
NeoEats domain APIs, and a React Saga Console.
```

## Suggested Topics

```text
fastapi
python
ai-orchestration
workflow-engine
saga-pattern
llmops
redis
postgresql
pgvector
react
typescript
vite
```

## What To Highlight

- Runtime design: module registry, flow compilation, validation, release records,
  run creation, timeline inspection, artifact extraction, and SSE event replay.
- Extension tooling: Contract v1 manifests, a shared Module SDK, structured CLI
  diagnostics, subprocess sandbox evidence, package fingerprints, and guarded
  lifecycle transitions with an optional Docker hardened sandbox and signed
  publication gate that rejects observed Python-level capability violations.
- Saga depth: version registry, typed flow handlers, retry/timeouts,
  idempotency, distributed locking, compensation-oriented state model.
- Domain proof: NeoEats uses the runtime for pantry, recipes, receipt
  confirmation, vision metadata, memory controls, and order saga status.
- Safety: public mode disables dev/test surfaces, legacy auth, permissive CORS,
  and prompt-test routes; production requires admin and pepper secrets.
- Testability: deterministic stub provider mode allows CI and reviewer runs
  without real LLM keys.
- UI layer: Saga Console demonstrates how the backend control plane can be used
  by operators, not only called by scripts.

## Best Reviewer Path

1. Start with `README.md` for the product narrative.
2. Run `python scripts/run_portfolio_demo.py` and follow `DEMO.md`.
3. Open `app/main.py` to understand app factory wiring.
4. Review `app/api/console/` for the modules/flows/runs control plane.
5. Review `app/core/realtime/sagas/orchestrator.py` and
   `app/core/realtime/sagas/flows/flow_executor.py` for runtime mechanics.
6. Review `app/core/neoeats_blocks.py`, `app/api/receipts.py`, and
   `app/api/inventory_orders_vision_routes.py` for the domain vertical.
7. Review `tests/unit/test_console_runtime_api.py`,
   `tests/unit/realtime/test_flow_executor_saga.py`, and NeoEats unit tests as
   proof points.
8. Optionally open `saga-console/src/` to see the operator UI surface.

## Demonstrable Flows

- Module lifecycle: list, inspect, validate, release, run in stub mode.
- Flow lifecycle: compile graph, validate, release, run, inspect timeline and
  artifacts.
- NeoEats recipe loop: normalize inventory, generate recipe, compile strict
  card, validate constraints.
- Receipt loop: analyze receipt, confirm items, update storage and memory events.
- Order loop: initialize order saga, inspect order status and event stream.

## Portfolio Patches Applied In This Pass

- Replaced the root README with a portfolio-first project overview, review
  guide, local setup, test commands, GitHub description, topics, and limitations.
- Updated `pyproject.toml` package description to match the product.
- Added ignore rules for SQLite WAL/SHM files, frontend `node_modules`, Vite
  build output, and TypeScript build-info files.
- Cleaned corrupted startup log strings in `app/infrastructure/router_registration.py`.
- Aligned router registration with its test policy by suppressing only
  `ImportError`, not broad `Exception`, in the agent-router block.
- Updated stale portfolio references from the old single-file console runtime
  path to the current `app/api/console/` package.
- Redacted exact historical secret values from secret-management documentation
  and changed the verification script to detect live-looking Gemini keys without
  embedding known leaked values.
- Added `scripts/run_portfolio_demo.py`, a one-command local launcher that starts
  the backend and Saga Console in deterministic stub mode, seeds a gallery flow,
  chooses free local ports, and supports a non-interactive smoke test.
- Reframed README/DEMO docs around the reviewer path instead of full production
  deployment.
- Fixed the Saga Console demo path: dev `/v1/me`, flow sandbox status,
  blueprint-to-graph input preservation, and module stub runs without a realtime
  orchestrator.

## Remaining Publication Risks

- The working tree still contains a large historical cleanup delta. Before
  publishing, commit or intentionally remove tracked generated artifacts,
  especially previously tracked `node_modules` and SQLite runtime files.
- Some historical docs still contain old architecture wording. The new README,
  `DEMO.md`, and this brief should be the public entry points until those docs
  are normalized.
- `requirements.txt` is not the canonical runtime source; `pyproject.toml` and
  `requirements.lock` are more reliable for setup.
- Active run cancellation is not implemented yet; the API currently reports
  `cancel_not_supported_yet`.
- Real LLM/vision behavior depends on external provider keys and should be
  shown only through secrets-gated smoke tests.

## Suggested Portfolio Summary

Seed Server is a production-minded AI orchestration backend built with FastAPI.
It provides a module and flow runtime, saga-based execution, provider and budget
gates, Redis-backed realtime infrastructure, and a domain vertical called
NeoEats that exercises the runtime through inventory, receipt, recipe, cooking,
memory, and order workflows. A React Saga Console gives reviewers a concrete
operator-facing view into modules, flows, runs, and provider profiles.
