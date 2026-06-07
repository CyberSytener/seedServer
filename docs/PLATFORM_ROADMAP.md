# Seed Platform Development Roadmap

Last updated: 2026-06-07

## Product Thesis

Seed Platform explores one central idea:

> Systems can be decomposed into independently described modules, connected
> through shared contracts, and extended by AI through a controlled validation
> and publication process.

The target product is not an AI that writes arbitrary code directly into the
runtime. It is a platform that gives AI enough structured context to propose a
module, then requires the proposal to pass contracts, tests, sandbox execution,
policy checks, and human approval before publication.

## Target End-To-End Scenario

```text
User describes a capability
-> AI proposes a module manifest, implementation, tests, and example flow
-> platform validates the contract
-> platform runs tests and sandbox checks
-> AI repairs rejected proposals using structured feedback
-> human approves publication
-> module appears in the registry and Saga Console
-> module can be composed into a workflow without changing platform core
```

The roadmap is complete when this scenario is reliable, observable, and easy
to demonstrate.

## Delivery Principles

- Keep the portfolio demo working after every phase.
- Prefer explicit contracts over runtime inference.
- AI may propose and repair; policy and humans decide whether to publish.
- New modules must not require edits to platform core.
- Every lifecycle transition must produce evidence.
- Historical capabilities may remain in the repository, but only the declared
  active surface is maintained as a release gate.

## Phase 0 - Stabilize The Platform Foundation

**Goal:** create a predictable development baseline before adding a new module
contract or AI-generated code.

**Status:** Complete.

### Scope

- Establish GitHub `main` as the canonical source and use a clean local clone
  for new work.
- Declare active, candidate, experimental, and legacy surfaces.
- Separate mandatory portfolio checks from broad experimental checks.
- Document architectural decisions and the development roadmap.
- Keep a one-command reviewer demo and a reproducible quality gate.

### Deliverables

- `docs/ACTIVE_PLATFORM_SCOPE.md`
- `docs/TEST_STRATEGY.md`
- `docs/adr/`
- `scripts/run_quality_gate.py`
- updated `SOURCE_OF_TRUTH.md`, `README.md`, and CI documentation

### Exit Criteria

- A new contributor can identify the active platform surface in under ten
  minutes.
- `python scripts/run_quality_gate.py portfolio` passes from a clean clone.
- `python scripts/run_quality_gate.py integration` passes in the supported CI
  environment.
- Experimental failures cannot silently block the supported demo.
- Architectural decisions for contracts and AI publication are recorded.

## Phase 1 - Module Contract v1

**Goal:** describe not only module data shapes, but also execution behavior,
permissions, operational limits, and compatibility.

**Status:** In progress. The first vertical slice provides the Contract v1
schema, Python validation model, legacy adapter, registry integration, and
input/output compatibility checks. The second vertical slice applies those
checks to flow compile, validation, sandbox, run, and release gates. The third
vertical slice adds explicit execution adapters and migrates the active Gallery
blocks to full Contract v1 manifests with runtime-schema drift protection.

### Contract Areas

- Identity: stable ID, semantic version, contract version, ownership.
- Data: JSON Schema input, output, and typed error payloads.
- Execution: pipeline, runtime adapter, timeout, retry policy, idempotency,
  determinism.
- Effects: side effects, compensation support, network and filesystem access.
- Security: required capabilities, secret references, trust level.
- Resources: memory, concurrency, cost units, provider requirements.
- Compatibility: accepted contract versions and module dependencies.
- Evidence: tests, examples, documentation, and lifecycle state.

### Deliverables

- Module Contract v1 JSON Schema.
- Python models and validation errors.
- migration adapter for the existing `general_assistant.yaml`.
- compatibility checker for connected module inputs and outputs.
- contract-focused unit tests and documentation.
- full Contract v1 manifests for the active Gallery flow blocks.
- direct-run and flow-adapter routing guards.

### Exit Criteria

- Invalid manifests fail with precise machine-readable errors.
- Existing demo modules are represented using Contract v1.
- The runtime refuses undeclared capabilities and incompatible connections.
- Contract versions can evolve without silently breaking existing modules.

## Phase 2 - Module SDK And CLI

**Goal:** make module creation predictable for both humans and AI.

**Status:** In progress. The first vertical slice provides the stable SDK
context/result/error interfaces, a standard generated module package, structured
validation and golden-case reports, a Python dependency allowlist, and
`seed module create|validate|test`. The second vertical slice adds
`seed module sandbox`: isolated-interpreter subprocess execution, sanitized
environment, wall timeout, platform-aware resource limits, and structured
sandbox evidence. The third vertical slice adds package fingerprints,
append-only local evidence, qualification/status commands, and guarded
lifecycle transitions through `approved`. The fourth slice adds HMAC-signed
evidence verification and a dedicated publish command that requires signed
hardened-isolation evidence. SDK modules remain outside active flows until a
hardened runtime execution path is integrated with the flow engine.

### Deliverables

- [x] standard module package layout;
- [x] `ModuleHandler` interface and typed execution context;
- [x] input/output validation wrappers;
- [x] standard error envelope;
- [x] dependency allowlist;
- local commands:

```text
seed module create    [done]
seed module validate  [done]
seed module test      [done]
seed module sandbox   [done]
seed module qualify   [done]
seed module status    [done]
seed module transition [done]
seed module publish   [done: gate]
seed module deprecate [done: gate]
seed module reject    [done: gate]
seed module history   [done]
seed module rejections [done]
```

### Exit Criteria

- A developer can create and validate a module without editing platform core.
- Generated modules use the same SDK as human-authored modules.
- The SDK emits structured diagnostics suitable for an AI repair loop.

## Phase 3 - Module Lifecycle And Evidence

**Goal:** make module state transitions explicit and auditable.

**Status:** In progress. The first vertical slice provides fingerprint-bound
validation, test, sandbox, and transition evidence; readiness assessment; and
ordered CLI transitions through human approval. The second slice adds optional
HMAC evidence signatures and signed allow/block publication decisions. The
third slice adds signed immutable package snapshots and semantic-version
conflict prevention. The fourth slice adds signed deprecation decisions bound
to immutable release snapshots. The fifth slice adds signed durable rejected
candidate snapshots and structured repair context. Asymmetric signing, key
rotation, a publish gate API, and the automated AI repair loop remain open.

### Lifecycle

```text
Draft -> Validated -> Tested -> Sandboxed -> Approved -> Published -> Deprecated
```

### Deliverables

- [x] lifecycle state model and transition guards through approval;
- [x] append-only validation, test, sandbox, and transition reports;
- [x] signed publish decision and dedicated CLI gate;
- [x] immutable published version history;
- [x] signed deprecation records bound to published versions;
- [x] signed durable rejection records with actor, reason, and repair context;
- publish gate API.

### Exit Criteria

- A module cannot skip required lifecycle stages.
- Every published version links to evidence that justified publication.
- Rejected versions remain inspectable and repairable.

## Phase 4 - AI Module Builder

**Goal:** let AI propose modules using a bounded, explicit context pack.

### Context Pack

- Module Contract schema and SDK documentation.
- Available types, capabilities, and dependencies.
- Existing module summaries and compatibility information.
- Good and bad examples.
- Validation errors and sandbox reports from previous attempts.

### Deliverables

- natural-language module proposal API;
- manifest, implementation, test, README, and example-flow generation;
- structured repair loop;
- generation budgets and attempt limits;
- provenance records for generated artifacts.

### Exit Criteria

- AI can generate a small useful module that reaches `Sandboxed`.
- Failed proposals are repaired from structured feedback.
- Generated code cannot publish itself.

## Phase 5 - Sandbox And Publish Gate

**Goal:** verify declared behavior against observed behavior before approval.

**Status:** In progress. The publish policy, signed decision format, and
optional Docker hardened adapter are implemented. Python-level operation
observation now blocks undeclared filesystem, network, and process events and
feeds the publish gate. Sandbox evidence now records secret/dependency policy,
and publication fails closed when a module needs an unavailable secret broker
or verified dependency bundle. Native/syscall observation, broker/bundle
implementation, remote attestation, and stronger secret isolation remain open.

### Deliverables

- deny-by-default network and filesystem policy;
- [x] container-level deny-by-default network and filesystem containment;
- [x] time, memory, process, and CPU limits;
- [x] fail-closed dependency and secret requirement reports;
- verified dependency bundle builder and secret broker;
- [x] declared-vs-enforced capability report;
- [x] observed Python operation-level capability report;
- deterministic test fixtures;
- [x] signed publication recommendation.

### Exit Criteria

- Undeclared Python-level network and filesystem access causes rejection;
  unresolved secret/dependency requirements also cause rejection.
- Timeouts and resource violations are visible in the report.
- The publish gate explains why a module is accepted or rejected.

## Phase 6 - Saga Console Module Workshop

**Goal:** make the complete lifecycle understandable and operable through the
UI.

### Deliverables

- module request form;
- generated manifest/code/test review;
- validation and sandbox report views;
- approve, reject, regenerate, and deprecate actions;
- version history and compatibility view;
- flow suggestions using the new module.

### Exit Criteria

- A reviewer can follow the full module lifecycle without using the terminal.
- Dangerous actions require an explicit confirmation and leave an audit event.
- Errors are actionable enough to guide a repair.

## Phase 7 - Reference Demonstration

**Goal:** prove the thesis with one polished scenario.

### Scenario

1. Request a job-ranking module.
2. AI generates a proposal with an invalid output contract.
3. Contract validation rejects it with structured diagnostics.
4. AI repairs the proposal.
5. Tests and sandbox pass.
6. A human approves the module.
7. The module appears in the registry and gallery.
8. A workflow uses it and exposes its run evidence.

### Exit Criteria

- The scenario is deterministic in stub mode.
- It can be demonstrated in under five minutes.
- Every transition is visible in Saga Console.
- The repository contains an automated end-to-end acceptance test.

## Longer-Term Opportunities

- module marketplace and trust scores;
- automatic compatibility and flow suggestions;
- cost, latency, and reliability planning;
- contract migration tooling;
- multi-agent generation and review;
- signed third-party module packages.
