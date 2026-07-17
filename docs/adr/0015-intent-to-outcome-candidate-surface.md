# ADR 0015: Intent-to-Outcome Candidate Surface

- Status: Accepted
- Date: 2026-07-17

## Context

Seed Platform now has an Intent-to-Outcome manifesto, a staged implementation
plan, and a code-grounded server alignment audit. The proposed capability adds a
reusable loop for confirmed intent, immutable evidence, falsifiable hypotheses,
ranked opportunities, bounded action proposals, and measured outcomes.

The repository already has stable Module Contract v1, Module SDK, sandbox,
lifecycle evidence, flow validation, Saga execution, ActionRouter, and Saga
Console foundations. It does not yet have universal Intent-to-Outcome contracts,
a supported Module SDK execution path inside flows, or a canonical
ActionProposal-to-policy-to-runtime boundary.

Starting implementation without an explicit scope decision would make it easy to
mix universal platform concepts with retail, crypto, sensor, or Companion
requirements, or to treat experimental code as an Active product commitment.

## Decision

- Intent-to-Outcome is accepted as a **Candidate** platform surface owned by the
  Seed Platform subsystem.
- The universal Candidate language is limited to:
  - intent;
  - evidence;
  - hypothesis;
  - opportunity;
  - action proposal;
  - outcome.
- The initial package boundaries are:

  ```text
  app/contracts/opportunity/
  app/domain/opportunity/
  app/services/opportunity/
  tests/unit/opportunity/
  tests/integration/opportunity/
  tests/fixtures/opportunity/
  ```

- `app/contracts/opportunity/` owns portable versioned data contracts.
- `app/domain/opportunity/` owns pure deterministic policies and lifecycle
  transitions.
- `app/services/opportunity/` owns application orchestration against protocols;
  it must not import FastAPI application state or concrete infrastructure
  adapters.
- Retail footwear is the first deterministic reference vertical, but retail
  fields do not belong in universal contracts.
- Crypto, Home, Observer, sensors, robotics, and Companion remain independent
  vertical packs with separate permissions, adapters, threat models, and ADRs.
- The existing job-specific `market_scanner` keeps its current meaning and is not
  generalized into the new platform surface.
- Candidate implementation reuses Module Contract v1, Module SDK, sandbox,
  lifecycle evidence, FlowContractValidator, FlowExecutorSaga, ActionRouter,
  Saga safety, and Saga Console. It must not introduce a second registry,
  workflow engine, Saga implementation, or publication lifecycle.
- This ADR authorizes package boundaries and pure Candidate contracts only. It
  does not authorize:
  - API routes;
  - database tables;
  - live providers or external sources;
  - real financial, public, physical, or privacy-sensitive actions;
  - changes to `app/main.py`;
  - promotion to the Active platform surface.
- A Candidate-specific quality gate must exist before Candidate implementation is
  considered verified.
- Promotion to Active requires:
  1. stable universal contracts;
  2. a deterministic fixture reference flow;
  3. documented failure behavior;
  4. focused release-blocking tests;
  5. safe SDK-module flow execution;
  6. a mandatory ActionProposal policy boundary for consequential actions;
  7. an independent Cold Review;
  8. a follow-up promotion ADR.

## Consequences

- Intent-to-Outcome can evolve without changing the promises of the current
  Active platform.
- Universal contracts remain reusable across verticals instead of becoming a
  retail or crypto schema.
- Codex receives a stable location and dependency direction for the new work.
- Existing platform gates remain authoritative while a focused Candidate gate is
  developed.
- Live integrations and consequential actions remain blocked until their
  remediation and authorization gates are satisfied.
- The Candidate surface can be removed without an Active-platform migration until
  a later ADR promotes it.

## Verification

- `docs/ACTIVE_PLATFORM_SCOPE.md` identifies Intent-to-Outcome as Candidate.
- The package skeleton imports without registering routes, modules, providers,
  database schema, or runtime behavior.
- Boundary tests reject forbidden infrastructure imports in the new package
  namespaces.
- `python scripts/run_quality_gate.py portfolio` remains green.
- No files under `app/main.py`, runtime wiring, module registry, Saga runtime, or
  active Gallery flows are changed by the package-boundary task.
