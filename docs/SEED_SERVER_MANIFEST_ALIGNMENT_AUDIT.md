# Seed Server Manifest Alignment Audit and Transformation Plan

Status: Candidate architecture audit  
Owner: Seed Platform  
Audit date: 2026-07-17  
Audited ref: `main@7613c4251421101238c77996fa4c98b04081140a`  
Target repository: `CyberSytener/seedServer`  
Normative product documents:

- `docs/INTENT_TO_OUTCOME_MANIFEST.md`;
- `docs/INTENT_TO_OUTCOME_IMPLEMENTATION_PLAN.md`;
- `AGENTS.md`.

## 1. Purpose

This document answers two questions:

1. How closely does the current Seed Server architecture match the Intent-to-Outcome manifesto?
2. What must be transformed or repaired before the staged implementation can be executed safely?

The audit is code- and contract-oriented. It does not treat historical reports as current commitments. It uses the canonical `main` branch, the active-scope policy, maintained platform roadmap, current Module Contract/SDK implementation, flow validation and execution code, ActionRouter, Saga runtime, persistence interfaces, startup wiring, artifact storage, and quality gates.

The audit does not claim that repository tests were executed in this session. GitHub source inspection was available; a local clone could not be created because the execution environment had no external DNS access. Existing test commands, test files, CI responsibilities, and implementation behavior were inspected directly.

## 2. Executive Verdict

The current Seed Server is a strong base for the manifesto, but it is not yet ready to execute the full proposed loop without architectural remediation.

### Overall fit

| Area | Fit | Verdict |
| --- | ---: | --- |
| Platform governance and scope discipline | 9/10 | Strong |
| Module Contract v1 | 8.5/10 | Strong |
| Module SDK, sandbox, lifecycle, publication evidence | 8.5/10 | Strong |
| Flow contract validation | 7/10 | Useful but incomplete |
| Flow runtime | 6/10 | Good block runtime, missing SDK bridge |
| Saga reliability foundation | 7/10 | Strong mechanisms, centralized and unevenly wired |
| Action confirmation and policy boundary | 5/10 | Exists, but unsafe gaps remain |
| Universal Intent/Evidence/Opportunity/Outcome model | 1/10 | Intentionally not implemented yet |
| Persistence boundary for the manifesto | 4/10 | Protocols exist, migration discipline is insufficient |
| Artifact privacy, retention, and provenance storage | 3/10 | Prototype-level local storage |
| Candidate test and promotion gates | 7/10 | Good foundation, manifesto-specific gate missing |
| Overall readiness for deterministic fixture milestone | 7/10 | Viable after focused remediation |
| Readiness for live sources or consequential actions | 3/10 | No-go until safety work is complete |

### Primary conclusion

Seed should not be rewritten. The correct strategy is:

```text
preserve Contract v1, Module SDK, sandbox, lifecycle evidence, Saga core,
FlowContractValidator, FlowExecutor, and Saga Console

then add:

1. a safe execution bridge for SDK modules inside flows;
2. a canonical ActionProposal policy gateway;
3. durable confirmation recovery;
4. explicit migrations and repository protocols;
5. sensitivity-aware evidence/artifact storage;
6. candidate-specific release gates.
```

The first deterministic retail milestone remains realistic. Live sources, third-party messages, spending, trading, sensors, and physical actions must remain blocked until the relevant remediation gates are green.

## 3. Current Architecture as Implemented

The maintained platform currently has the following effective structure:

```text
FastAPI create_app / router registration
              |
              v
application and console APIs
              |
              +--> ModuleRegistry + FlowContractValidator
              |
              +--> ActionRouter
              |       |
              |       +--> direct executors
              |       +--> optional SagaOrchestrator
              |
              +--> Saga Console runtime
              |
              v
FlowExecutorSaga / BlockRegistry
              |
              v
built-in flow blocks

separate candidate path:

Module Contract v1 package
      -> Module SDK
      -> validate/test/sandbox/qualify/publish CLI
      -> immutable evidence and versions

but no supported runtime bridge from a published SDK module into FlowExecutorSaga.
```

This separation is the most important fact for the implementation plan. The SDK publication pipeline is mature, while the active flow runtime still executes `BlockRegistry` blocks.

## 4. What Already Matches the Manifesto

### 4.1 Scope and promotion discipline

The repository already distinguishes Active, Candidate, Experimental, and Legacy surfaces. Candidate promotion requires product responsibility, ownership, stable contracts, failure behavior, focused release-blocking tests, and an ADR.

This directly supports the manifesto requirement that Intent-to-Outcome begin as a Candidate surface.

### 4.2 Contract-first module model

`ModuleContractV1` already describes:

- stable identity and semantic version;
- pipeline and execution adapter;
- input and output JSON Schemas;
- typed error declarations;
- capabilities;
- side effects and compensation support;
- network and filesystem policy;
- secret references and trust level;
- resources, providers, cost units, and concurrency;
- compatibility and dependencies;
- lifecycle, evidence, prompt versions, rubric versions, and tests.

The explicit adapters `saga_orchestrator`, `block_registry`, and `module_sdk` are already part of the contract language. This is the correct base for vertical Intent-to-Outcome modules.

### 4.3 SDK and publication controls

The Module SDK and CLI already provide:

- package generation;
- contract validation;
- golden-case tests;
- isolated subprocess execution;
- optional hardened Docker execution;
- capability observation;
- package fingerprints;
- append-only evidence;
- guarded lifecycle transitions;
- signed publication decisions;
- immutable published versions;
- deprecation, rejection, and bounded repair context.

The manifesto should reuse this system rather than creating a separate agent or plugin lifecycle.

### 4.4 Flow contract checking

`FlowContractValidator` already:

- resolves module and block metadata;
- validates explicit field mappings;
- checks required producer fields;
- detects basic type incompatibility;
- rejects missing modules and missing execution adapters;
- emits machine-readable issues before execution.

This is a strong base for the manifesto's edge compatibility suite.

### 4.5 Saga reliability mechanisms

The Saga runtime already contains or declares:

- retries and backoff;
- idempotency;
- persistence across restarts;
- distributed locks;
- confirmation states;
- timeouts;
- compensation;
- circuit breakers;
- rate limiting;
- tracing, telemetry, metrics, and DLQ support.

The transformation plan must normalize how these mechanisms are invoked rather than replace them.

### 4.6 Deterministic test strategy

The maintained test strategy already separates:

- portfolio gate;
- integration gate;
- demo smoke;
- experimental gate;
- conditional real-provider smoke.

The portfolio gate deliberately avoids paid providers, PostgreSQL, Redis, and a Docker daemon. This is compatible with fixture-first Intent-to-Outcome development.

## 5. Manifest Alignment Matrix

| Manifest requirement | Current state | Alignment | Required action |
| --- | --- | --- | --- |
| Candidate surface with ADR | Supported by scope policy | Compliant | Add dedicated ADR |
| Universal typed domain contracts | Not implemented | Missing by design | Implement Phase 1 |
| New vertical modules use Contract v1 | Supported | Compliant | Create new stable IDs |
| SDK modules compose into flows | SDK and flow runtime are separate | Blocking gap | Add execution bridge |
| Explicit edge mappings | Implemented | Compliant | Extend tests for universal schemas |
| Deterministic fixture observers | Simulation and fixtures exist | Partial | Add retail fixture pack |
| Evidence provenance chain | Generic flow artifacts only | Partial | Add EvidenceItem contracts and repository |
| Independent evidence critic | Not implemented | Missing by design | Add separate module/rubric |
| Deterministic opportunity scoring | Not implemented | Missing by design | Add pure policy engine |
| Semantic ActionProposal before execution | Existing `Action` is executor-oriented | Blocking gap | Add proposal gateway |
| Consequential action confirmation | Present | Partial | Remove bypasses and make recovery durable |
| Explicit expiry and cost ceiling | Partial/implicit | Missing at policy boundary | Enforce in ActionProposal gateway |
| Idempotency | Present in ActionRouter and Saga | Partial | Bind to proposal key and durable state |
| Compensation and recovery | Present in Saga | Partial | Require capability-specific declaration |
| Append-only negative outcomes | No universal outcome store | Missing | Add OutcomeRecord repository |
| Tenant-scoped persistence | Present inconsistently | Partial | Add repository protocols and migrations |
| Sensitive-data retention classes | Not enforced by artifact store | Blocking for live/private data | Add artifact/evidence policy |
| No raw LLM actuator/provider commands | Not universally enforced | Partial | Semantic proposal boundary |
| Saga Console evidence inspection | Generic timeline/artifacts exist | Partial | Add Candidate views and evidence graph |
| Candidate release-blocking tests | General gates exist | Partial | Add focused candidate gate |
| Live sources only after replay fixtures | Policy supports it | Compliant in docs | Enforce adapter contract and tests |

## 6. Critical Findings

Severity levels:

- **P0** — blocks the deterministic reference architecture or creates a direct safety bypass;
- **P1** — must be repaired before persistence, live sources, or consequential actions;
- **P2** — important maintainability or hardening work that may follow the first closed-loop proof.

### A-01 — SDK modules cannot currently execute inside FlowExecutorSaga

**Severity:** P0  
**Affected paths:**

- `app/services/flow_contract_validator.py`;
- `app/core/realtime/sagas/flows/flow_executor.py`;
- `app/services/module_registry.py`;
- `app/module_sdk/`.

`ModuleContractV1` supports `pipeline: sdk_module` and `execution.adapter: module_sdk`. However, `FlowContractValidator.resolve_module()` marks a Contract v1 module executable only when its adapter is `block_registry` and its ID exists in the built-in block registry. `FlowExecutorSaga` constructs blocks directly through `BlockRegistry.create()`.

The platform roadmap also states that SDK modules remain outside active flows until a hardened runtime execution path is integrated.

**Risk:** Codex could duplicate every manifesto module as an internal block, bypass the SDK sandbox, or modify platform core for each vertical module.

**Required remediation:** introduce a stable flow module execution port with separate adapters for `block_registry` and `module_sdk`.

### A-02 — Flow cycles fail open to insertion order

**Severity:** P0  
**Affected path:** `app/core/realtime/sagas/flows/flow_executor.py`.

The topological sort returns insertion order when a cycle prevents a complete topological ordering.

**Risk:** an invalid cyclic graph may execute in a misleading order instead of being rejected before runtime. This breaks contract-first composition and may produce incorrect evidence.

**Required remediation:** cycle detection must return a stable `flow.cycle_detected` diagnostic and prevent execution.

### A-03 — ActionRouter accepts some unknown actions through a dummy specification

**Severity:** P0  
**Affected path:** `app/core/realtime/action_router.py`.

When no registered action specification exists, the router currently accepts an action if it appears in a hard-coded Saga list or metadata says user confirmation is required. It creates an internal `_DummySpec` whose only property is `requires_confirmation = True`.

**Risk:** confirmation is being treated as a substitute for an action contract. A model or integration may reach execution without a registered capability, cost policy, input schema, reversibility declaration, or measurement plan.

**Required remediation:** no consequential action may enter confirmation without a registered semantic action specification and a valid policy decision.

### A-04 — Confirmation state is not durably recoverable through the main confirmation path

**Severity:** P0 before real actions  
**Affected paths:**

- `app/core/realtime/action_router.py`;
- `app/core/realtime/pending_store.py`;
- `app/infrastructure/app_wiring.py`.

Pending actions are written to an optional Redis store and replicated to Redis, but `confirm_action()` looks up the action in the process-local `_pending_confirmations` dictionary. No recovery path was found that loads a pending action from durable state after process restart or on a second server instance.

**Risk:** a valid confirmation may fail after restart, while distributed state and local state disagree. A later workaround could create duplicate execution risk.

**Required remediation:** confirmation lookup, transition, and idempotency must use a `PendingActionRepository` as the source of truth; memory becomes a cache only.

### A-05 — Current `Action` is not the manifesto's `ActionProposal`

**Severity:** P0  
**Affected paths:**

- `app/models/realtime.py` and related realtime models;
- `app/core/realtime/action_router.py`;
- action specs and executors;
- Saga integration.

The current realtime `Action` path is designed to invoke named executors. It does not universally require:

- linked intent, evidence, hypothesis, and opportunity;
- semantic action type;
- policy version and decision;
- cost or maximum-loss ceiling;
- reversibility and compensation design;
- expected result and measurement plan;
- expiration;
- explicit sensitivity or external-contact class.

**Required remediation:** add `ActionProposalV1` as an upstream domain contract and a `ProposalPolicyGateway`. The gateway may emit an existing runtime `Action` only after validation and authorization.

### A-06 — Runtime code creates database schema

**Severity:** P1  
**Affected paths:**

- `app/infrastructure/db/sqlite.py`;
- `app/core/realtime/sagas/orchestrator.py`;
- other `ensure_*_table` initialization functions.

The SQLite adapter contains a very large embedded schema. Saga startup creates the DLQ table through `CREATE TABLE IF NOT EXISTS`. Other initialization paths also ensure tables during application startup.

**Risk:** schema ownership and rollback become unclear; migrations cannot be reviewed independently; Candidate persistence can silently appear during runtime.

**Required remediation:** introduce explicit versioned migrations. Runtime components may verify required schema but must not invent it at arbitrary call sites.

### A-07 — ArtifactStore is prototype-level and policy-blind

**Severity:** P1  
**Affected paths:**

- `app/core/realtime/sagas/artifact_store.py`;
- `app/core/realtime/sagas/flows/flow_executor.py`.

The store writes normalized JSON to `/tmp/seed_artifacts` using hash-addressed files. It has no tenant scope, sensitivity class, retention class, encryption policy, deletion control, access check, or durable metadata repository.

**Risk:** evidence or private data from future retail, crypto, sensor, public-camera, or Companion modules could be stored indefinitely in raw form.

**Required remediation:** define an `ArtifactRepository` protocol and policy envelope. The first adapter may remain local and deterministic but must understand tenant, sensitivity, retention, and deletion.

### A-08 — Artifact write failures are silently discarded

**Severity:** P1  
**Affected path:** `app/core/realtime/sagas/flows/flow_executor.py`.

`_store_artifact()` catches all exceptions and returns `None`.

**Risk:** a run can appear successful while the evidence needed to reconstruct it was not stored. This conflicts with the manifesto's evidence-first Definition of Done.

**Required remediation:** artifact policy must define whether an artifact is required or optional. Failure to store a required evidence artifact must fail the run with a stable diagnostic.

### A-09 — Saga type and adapter registration are centralized and hard-coded

**Severity:** P1  
**Affected paths:**

- `app/core/realtime/sagas/orchestrator.py`;
- `app/infrastructure/app_wiring.py`;
- `app/core/realtime/action_router.py`.

Saga timeout configuration, version registry, Saga-eligible action names, and adapter construction are centralized dictionaries and wiring code.

**Risk:** each new domain may require changes to platform core, contrary to the platform thesis that modules should compose without core edits.

**Required remediation:** use registries/factories behind stable protocols. The Intent-to-Outcome reference flow should use the generic `flow_executor` rather than adding a new hard-coded Saga type.

### A-10 — Optional infrastructure can silently disable important behavior

**Severity:** P1  
**Affected paths:**

- `app/infrastructure/app_wiring.py`;
- `app/infrastructure/router_registration.py`;
- selected startup initialization in `app/main.py`.

Router registration correctly suppresses only `ImportError`, which is good. However, realtime wiring still catches broad exceptions and disables SagaOrchestrator, Saga adapters, idempotency, event bus, pending store, or WebSocket gateway while allowing startup to continue.

**Risk:** an environment may look healthy but lose safety or durability mechanisms.

**Required remediation:** introduce explicit component readiness with classifications:

```text
required_for_active_surface
required_for_enabled_feature
optional
```

An enabled consequential feature must fail startup if its required policy, persistence, idempotency, or confirmation dependency is unavailable.

### A-11 — Database abstraction is too low-level for the manifesto

**Severity:** P1  
**Affected paths:**

- `app/core/interfaces/database.py`;
- SQLite and PostgreSQL adapters;
- application services using direct SQL.

Current protocols expose generic SQL methods. They are useful infrastructure boundaries but do not define domain invariants such as immutable evidence, supersession, tenant scoping, lifecycle transitions, or append-only outcomes.

**Required remediation:** introduce domain repository protocols above the generic database protocol.

### A-12 — Candidate-specific tests are not release-blocking yet

**Severity:** P0 before Candidate implementation  
**Affected paths:**

- `scripts/run_quality_gate.py`;
- `docs/TEST_STRATEGY.md`;
- future `tests/unit/opportunity/` and `tests/integration/opportunity/`.

The portfolio gate protects current active surfaces but contains no Intent-to-Outcome tests. The integration gate runs all integration tests and may be too broad for fast Candidate work.

**Required remediation:** add an `intent_to_outcome` or `candidate` gate after the package skeleton exists. Promotion to Active later requires moving the stable subset into the portfolio gate.

### A-13 — Prompt-injection marker detection is only a coarse guard

**Severity:** P2  
**Affected path:** `app/services/module_registry.py`.

The registry recursively rejects a small list of string markers. This is useful as a regression guard but not a complete trust boundary.

**Risk:** developers may incorrectly assume that marker filtering makes untrusted source text safe.

**Required remediation:** keep source text structurally separated from instructions, use bounded extraction schemas, record provenance, and test adversarial fixtures. Marker filtering remains defense-in-depth only.

### A-14 — Schema validation may fail open when `jsonschema` is unavailable

**Severity:** P1  
**Affected path:** `app/services/module_registry.py`.

When `Draft202012Validator` is unavailable, request validation checks only required top-level fields.

**Risk:** type, range, nesting, and additional-property constraints can be skipped in a degraded installation.

**Required remediation:** JSON Schema validation must be a required dependency for active/candidate module execution. Degraded fallback may support inspection, but not execution.

### A-15 — `main.py` remains a large composition root with mixed responsibilities

**Severity:** P2  
**Affected paths:**

- `app/main.py`;
- `app/infrastructure/app_wiring.py`;
- `app/infrastructure/router_registration.py`.

`main.py` has improved significantly and router registration has been extracted. It still initializes SQLite schema, seed data, Redis, providers, domain engines, realtime queues, plans, feature flags, and routes.

**Risk:** new Intent-to-Outcome code may be added directly to startup and deepen coupling.

**Required remediation:** create feature-specific composition functions and registries. No Intent-to-Outcome business logic belongs in `main.py`.

## 7. Target Transformation Architecture

The transformed architecture should be:

```text
Saga Console / API
        |
        v
Intent-to-Outcome application services
        |
        +--> IntentRepository
        +--> EvidenceRepository
        +--> OpportunityRepository
        +--> OutcomeRepository
        +--> ProposalPolicyGateway
        |
        v
universal domain contracts and policies
        |
        v
FlowContractValidator
        |
        v
FlowExecutorSaga
        |
        v
ModuleExecutionPort
        |
        +--> BlockRegistryExecutionAdapter
        +--> ModuleSDKExecutionAdapter
        |
        v
sandbox / adapters / external providers
```

Consequential actions use a separate transition:

```text
ActionProposalV1
      |
      v
ProposalPolicyGateway
      |
      +--> denied
      +--> needs_confirmation
      +--> approved_for_runtime
                  |
                  v
            runtime Action
                  |
                  v
          ActionRouter / Saga
                  |
                  v
             OutcomeRecordV1
```

## 8. Mandatory Remediation Track

The remediation tasks below are prerequisites inserted into the staged implementation plan. They do not replace the ITO tasks; they make those tasks executable on the current architecture.

### ITO-R001 — Reject cyclic and structurally invalid flow graphs

**Priority:** P0  
**Scope:**

- detect cycles in `FlowContractValidator` and/or compile stage;
- make `FlowExecutorSaga` reject incomplete topological order;
- emit stable diagnostics;
- add unit and integration tests.

**Exit gate:** no cyclic graph reaches node execution.

### ITO-R002 — Required-artifact failure semantics

**Priority:** P0/P1  
**Scope:**

- replace blanket artifact exception suppression;
- classify artifact kinds as required or optional;
- fail a run when required evidence cannot be stored;
- preserve an explicit diagnostic for optional artifact loss.

**Exit gate:** a successful reference run always has its required evidence chain.

### ITO-R003 — ModuleExecutionPort and adapter registry

**Priority:** P0  
**Scope:**

Create a stable interface such as:

```python
class ModuleExecutionPort(Protocol):
    async def execute(
        self,
        *,
        module_spec: dict,
        module_input: dict,
        context: dict,
    ) -> dict: ...
```

Add an adapter registry keyed by the Contract v1 execution adapter.

**Rules:**

- `FlowExecutorSaga` does not import SDK worker internals;
- domain modules do not import infrastructure;
- execution adapter selection is contract-driven;
- missing adapter fails before execution.

### ITO-R004 — BlockRegistry execution adapter

**Priority:** P0  
**Scope:** move current built-in block execution behind `ModuleExecutionPort` without changing existing Gallery behavior.

**Exit gate:** existing portfolio flow output remains unchanged and portfolio gate passes.

### ITO-R005 — Candidate Module SDK flow adapter

**Priority:** P0  
**Scope:**

- execute `module_sdk` packages through the existing isolated worker protocol;
- use deterministic subprocess mode for Candidate tests;
- enforce declared timeout, capabilities, filesystem, network, dependency, and secret policy;
- return structured ModuleResult and sandbox evidence references;
- do not claim Docker hardening when subprocess mode was used.

**Exit gate:** one fixture-only SDK module can execute as a FlowExecutor node without being duplicated in BlockRegistry.

### ITO-R006 — FlowContractValidator adapter awareness

**Priority:** P0  
**Scope:**

- mark `module_sdk` modules executable only when the candidate SDK adapter is enabled;
- expose adapter availability in validation output;
- keep publication/lifecycle requirements explicit;
- reject draft/unqualified modules when policy requires a qualified package.

### ITO-R007 — Remove unknown-action dummy specification

**Priority:** P0  
**Scope:**

- delete `_DummySpec` fallback;
- require a registered action specification;
- require declared capabilities and semantic input schema;
- add negative tests for metadata-only confirmation attempts.

**Exit gate:** confirmation cannot authorize an unregistered action.

### ITO-R008 — Durable PendingActionRepository

**Priority:** P0 before simulated confirmation milestone  
**Scope:**

- define repository protocol;
- use Redis implementation where available and deterministic memory implementation for tests;
- make confirmation lookup and state transition repository-backed;
- support restart/multi-instance recovery;
- use compare-and-set or equivalent idempotent transition.

**Exit gate:** a pending action can be confirmed exactly once after router reconstruction.

### ITO-R009 — ProposalPolicyGateway

**Priority:** P0  
**Dependency:** `ActionProposalV1` contract.

**Scope:**

- validate proposal linkage, capabilities, permissions, expiry, cost ceiling, reversibility, and measurement plan;
- produce a typed policy decision;
- map only approved proposals to runtime `Action`;
- keep runtime executors unaware of LLM prose.

**Exit gate:** no Intent-to-Outcome action reaches ActionRouter except through the gateway.

### ITO-R010 — Explicit migration framework

**Priority:** P1 before Phase 4  
**Scope:**

- versioned migration registry;
- applied-migration table;
- development rollback policy;
- startup schema verification;
- move new opportunity tables out of arbitrary runtime creation.

Existing legacy schema does not have to be rewritten in the same PR. New Intent-to-Outcome tables must use the migration framework from their first commit.

### ITO-R011 — Domain repository protocols

**Priority:** P1  
**Scope:**

- `IntentRepository`;
- `EvidenceRepository`;
- `HypothesisRepository`;
- `OpportunityRepository`;
- `ActionProposalRepository`;
- `OutcomeRepository`.

Enforce tenant scope, immutability/supersession, append-only outcome history, and lifecycle transition rules above raw SQL.

### ITO-R012 — Policy-aware ArtifactRepository

**Priority:** P1 before persistence/live sources  
**Scope:**

- tenant scope;
- sensitivity and retention class;
- content hash;
- deletion/expiry;
- normalized structured evidence by default;
- optional encrypted local adapter later;
- deterministic in-memory adapter for tests.

### ITO-R013 — Component readiness and fail-closed wiring

**Priority:** P1 before real actions  
**Scope:**

Classify components as:

```text
required_for_active_surface
required_for_enabled_feature
optional
```

An enabled action feature must not silently fall back from durable idempotency, pending-action storage, policy, or Saga persistence to an unsafe mode.

### ITO-R014 — Candidate quality gate

**Priority:** P0 before Phase 1 is considered verified  
**Scope:** add a focused gate to `scripts/run_quality_gate.py`, for example:

```bash
python scripts/run_quality_gate.py intent-to-outcome
```

Initial contents:

- universal contract tests;
- transition and scoring tests;
- flow-cycle and adapter-selection tests;
- proposal policy denial tests;
- deterministic fixture module tests;
- confirmation recovery tests when introduced.

Promotion to Active later moves stable critical tests into the portfolio gate.

### ITO-R015 — Composition-root cleanup

**Priority:** P2  
**Scope:**

- feature-specific wiring functions;
- adapter factories and registries;
- no new domain engine initialization in `main.py`;
- explicit readiness report.

This work must be sliced and must not become a broad rewrite.

## 9. Revised Implementation Sequence

The original implementation plan remains valid, with the following dependency corrections.

### Wave A — Documentation and safe package boundary

```text
merge documentation PR
ITO-001 Candidate-surface ADR
ITO-002 package/test skeleton
ITO-R001 cycle rejection
ITO-R014 candidate quality-gate skeleton
```

### Wave B — Universal language and pure policies

```text
ITO-101 shared primitives
ITO-102 IntentContextV1
ITO-103 EvidenceItemV1
ITO-104 HypothesisV1
ITO-105 OpportunityV1
ITO-106 ActionProposalV1
ITO-107 OutcomeRecordV1
ITO-108 transition policy
ITO-109 deterministic scoring
```

These tasks can proceed without the SDK-flow bridge because they are pure domain work.

### Wave C — Runtime bridge before manifesto modules

```text
ITO-R003 ModuleExecutionPort
ITO-R004 BlockRegistry adapter
ITO-R005 Module SDK flow adapter
ITO-R006 adapter-aware flow validation
ITO-R002 required artifact semantics
```

No Phase 2 SDK module may be advertised as flow-executable before Wave C is green.

### Wave D — Action safety before reference confirmation

```text
ITO-R007 remove unknown-action fallback
ITO-R008 durable pending-action repository
ITO-R009 ProposalPolicyGateway
ITO-R013 fail-closed component readiness
```

The simulated action in Phase 3 must use this path. It must not add another one-off confirmation implementation.

### Wave E — Fixture modules and retail closed loop

```text
ITO-201 through ITO-209
ITO-301 through ITO-305
```

The first milestone is complete only after the existing portfolio gate, integration gate, Candidate gate, demo smoke, and Saga Console build are green.

### Wave F — Persistence hardening

```text
ITO-R010 migration framework
ITO-R011 domain repositories
ITO-R012 ArtifactRepository
ITO-401 through ITO-405
```

### Wave G — Live sources and bounded external effects

```text
ITO-501 through ITO-504
ITO-601 through ITO-603
```

Live sources require replay fixtures and authorization metadata. Consequential external effects require a separate ADR and threat model.

### Wave H — Domain-general proof

```text
ITO-701 through ITO-704
```

The crypto pack remains strictly read-only. It proves contract reuse; it does not prove trading performance.

## 10. PR-Sized Backlog

The following sequence is recommended after the documentation PR is merged.

| Order | Task | Expected paths | Risk |
| ---: | --- | --- | --- |
| 1 | ITO-001 Candidate ADR | `docs/adr/` | Low |
| 2 | ITO-002 package/test skeleton | `app/contracts/opportunity`, `app/domain/opportunity`, tests | Low |
| 3 | ITO-R001 flow cycle rejection | validator, flow executor, focused tests | Medium |
| 4 | ITO-R014 Candidate gate skeleton | quality script, test strategy | Low |
| 5 | ITO-101 shared primitives | opportunity contracts/tests | Medium |
| 6 | ITO-102/103 intent and evidence contracts | contracts/schemas/fixtures | Medium |
| 7 | ITO-104/105 hypothesis and opportunity | contracts/policies/tests | Medium |
| 8 | ITO-106/107 proposal and outcome | contracts/schemas/tests | High |
| 9 | ITO-108/109 transitions and scoring | domain policies/tests | Medium |
| 10 | ITO-R003 execution port | runtime interfaces/tests | High |
| 11 | ITO-R004 block adapter | FlowExecutor/registry/tests | High |
| 12 | ITO-R005 SDK flow adapter | SDK runtime bridge/tests | Very high |
| 13 | ITO-R006 validator adapter awareness | validator/registry/tests | Medium |
| 14 | ITO-R002 required artifact semantics | flow executor/artifact tests | Medium |
| 15 | ITO-R007 registered action requirement | ActionRouter/spec/tests | High |
| 16 | ITO-R008 durable confirmation | pending repository/router/tests | Very high |
| 17 | ITO-R009 policy gateway | services/domain/realtime tests | Very high |
| 18 | ITO-201 onward | module packages and reference flow | Medium after prerequisites |

Do not combine tasks 10–17 into one PR. They modify separate trust boundaries and require independent Cold Review.

## 11. Required New Test Families

### Flow correctness

- cycle rejection;
- missing execution adapter;
- unavailable SDK runtime;
- module lifecycle not eligible for execution;
- incompatible field mapping;
- required evidence artifact failure;
- deterministic parallel-node output ordering.

### Action safety

- unknown action rejected even when metadata asks for confirmation;
- expired proposal denied;
- permission mismatch denied;
- cost ceiling violation denied;
- proposal without measurement plan denied;
- confirmation after router restart succeeds exactly once;
- duplicate confirmation cannot duplicate execution;
- disabled Redis or policy dependency fails closed when feature is enabled.

### Persistence and privacy

- tenant isolation;
- immutable evidence supersession;
- negative outcomes retained;
- retention expiry;
- sensitive artifact deletion;
- no raw private source retention by default;
- migration applied exactly once;
- schema mismatch blocks enabled feature startup.

### SDK flow execution

- fixture SDK module executes through stable SDK only;
- undeclared filesystem/network/process operation denied;
- timeout visible;
- malformed output fails schema validation;
- subprocess evidence is never mislabeled as Docker hardened;
- package fingerprint mismatch prevents execution where qualification is required.

## 12. Architecture Decisions That Must Remain Unchanged

The transformation must not:

- replace Module Contract v1;
- create a second module registry;
- create a second workflow engine;
- create a second Saga implementation;
- bypass Module SDK qualification;
- make an LLM a policy authority;
- generalize the existing job `market_scanner` by changing its meaning;
- add retail, crypto, sensor, or Companion fields to universal contracts;
- put Intent-to-Outcome business logic in `app/main.py`;
- introduce live sources before fixtures and replay;
- introduce real spending, trading, public messages, or device control before confirmation and threat-model gates.

## 13. Go/No-Go Gates

### Gate G0 — Documentation accepted

- manifesto, execution plan, AGENTS rules, and this audit are merged;
- Candidate ADR task is approved to begin.

### Gate G1 — Pure domain foundation

- universal contracts, transitions, and scoring are deterministic;
- Candidate gate is green;
- no infrastructure dependency in domain tests.

### Gate G2 — Safe module composition

- SDK modules execute through ModuleExecutionPort;
- cycles are rejected;
- required evidence cannot disappear silently;
- existing Gallery remains green.

### Gate G3 — Safe action simulation

- unregistered actions are rejected;
- ProposalPolicyGateway is mandatory;
- confirmation is durable and exactly-once;
- simulated action leaves audit and outcome evidence.

### Gate G4 — First milestone

- deterministic retail closed loop passes from a clean environment;
- portfolio, integration, Candidate, smoke, and console build gates pass;
- independent Cold Review approves reproducibility and safety.

### Gate G5 — Persistence

- migrations, repositories, tenant isolation, retention, correction, deletion, and negative outcomes are tested.

### Gate G6 — Live observation

- source authorization, terms, secrets, rate limits, freshness, outage behavior, injection isolation, and replay fixtures are verified.

### Gate G7 — External effect

- dedicated ADR and threat model;
- explicit capability and confirmation;
- cost ceiling, expiry, idempotency, recovery, and outcome measurement;
- default installation cannot perform the effect automatically.

## 14. Immediate Recommendation

The documentation branch should be merged as a documentation-only Candidate proposal after review.

The first code branch should not attempt retail modules. It should implement:

```text
ITO-001 — Candidate-surface ADR
ITO-002 — package and test skeleton
```

The next independent code branch should implement:

```text
ITO-R001 — reject cyclic flow graphs
```

This ordering establishes the Candidate boundary, creates the domain location, and repairs a concrete correctness bug before new flows depend on it.

## 15. Definition of Architecture Alignment

Seed Server is sufficiently aligned with the manifesto when all of the following are true:

1. universal domain contracts exist independently of infrastructure;
2. SDK modules can execute in flows without becoming built-in blocks;
3. invalid flow graphs fail before execution;
4. every recommendation is reconstructable from immutable evidence;
5. every consequential runtime action originates from an approved ActionProposal;
6. confirmation and idempotency survive process restart;
7. required evidence storage failure cannot be hidden;
8. new schemas use explicit migrations;
9. tenant, sensitivity, and retention policies are enforced by repositories;
10. Candidate tests have a dedicated gate;
11. existing active portfolio behavior remains green;
12. vertical packs add modules and adapters without rewriting platform core.

At that point, Intent-to-Outcome is not merely documented on top of Seed. It is a native, contract-governed capability of the Seed architecture.