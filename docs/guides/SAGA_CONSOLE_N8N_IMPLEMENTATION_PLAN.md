# Saga Console as n8n - Implementation Plan

## Goal
Build Saga Console as a single control plane for:
- module registry and release lifecycle,
- flow authoring and validation,
- run execution and timeline visibility,
- runtime operations and artifacts review.

## Current Increment (implemented)
### API facade
- `GET /v1/modules`
- `GET /v1/modules/{module_id}`
- `POST /v1/modules/{module_id}/validate`
- `POST /v1/modules/{module_id}/release`
- `GET /v1/flows`
- `GET /v1/flows/{flow_id}`
- `POST /v1/flows/{flow_id}/validate`
- `POST /v1/flows/{flow_id}/release`
- `POST /v1/runs` (target type: `module` or `flow`, mode: `stub|real`)
- `GET /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/events` (SSE replay)
- `GET /v1/runs/{run_id}/artifacts`
- `POST /v1/runs/{run_id}/cancel` (MVP response, non-destructive)

### Auth bootstrap
- `GET /v1/auth/providers`

### Release/audit artifacts
- Module and flow release records are persisted under:
  - `.seed_artifacts/console/releases/modules/<module_id>/*.json`
  - `.seed_artifacts/console/releases/flows/<flow_id>/*.json`

## Domain mapping
### Module
- Source of truth: `modules/*.yaml`
- Runtime trigger path: existing mode execution (`/v1/modes/{mode_id}/run`) via facade.

### Flow
- Source of truth: existing blueprint store.
- Graph projection:
  - `nodes[]` from blueprint steps,
  - `edges[]` from `inputs.<field>.from` references.

### Run
- Module runs: backed by saga orchestrator state (via saga id).
- Flow runs: backed by run store records.
- Unified run detail shape exposes:
  - `timeline`,
  - `metrics`,
  - `artifacts`.

## Next phases
### A2 - Flow Builder MVP
- Add compile pipeline from UI graph -> `compiled_mode_payload` artifact.
- Introduce dedicated `FlowExecutorSaga` runtime type.
- Add assertion runner for simulation reports.

### A3 - Release governance
- Add release diffing and immutable version browsing.
- Add RBAC for publish/approve.
- Add CI hooks for module/flow validation gates.

