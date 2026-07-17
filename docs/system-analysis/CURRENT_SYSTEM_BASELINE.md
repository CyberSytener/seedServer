# Current Seed System Baseline And Route

Status: initial deep-analysis baseline  
Audit date: 2026-07-17  
Repository: `CyberSytener/seedServer`  
Starting ref: `main@eee84040fd8388e842d45b1e099dcd898574fd01`  
Target: `SEED-ITO-M3` with immediate checkpoint `ITO-102`  
Current readiness: **IMPLEMENTATION-READY for ITO-102; REMEDIATION-READY for the full M3 closed loop**

## 1. Evidence Boundary

This baseline combines:

- **Declared** evidence from maintained scope, test, roadmap, Agent, manifest, plan, and ADR documents;
- **Observed** evidence from direct GitHub source inspection of the repository entrypoints, quality-gate runner, project metadata, Candidate workflow, and recent merged PRs;
- **Verified** evidence from the green GitHub Actions histories recorded in merged PRs #2 through #5;
- **Inferred** architecture conclusions that still require the generated system-analysis inventory and later runtime-focused verification.

It does not claim that a repository-wide runtime trace or every historical test was executed in this analysis session. The `system-analysis` workflow and artifact introduced alongside this document will supply the first repeatable static inventory.

## 2. Executive Assessment

Seed Server should continue to evolve rather than be rewritten.

The platform already has the difficult foundations that are expensive to reproduce correctly:

- explicit Active, Candidate, Experimental, and historical scope;
- Contract v1 and a mature Module SDK lifecycle;
- deterministic stub mode and a reviewer-oriented portfolio path;
- Saga execution, compensation, idempotency, recovery, and observability mechanisms;
- flow contract validation and now fail-closed cycle rejection;
- separate Active and Intent-to-Outcome Candidate quality gates;
- the first universal Intent-to-Outcome primitives with versioned schema snapshots.

The dominant problem is not absence of components. It is that several strong subsystems remain adjacent rather than joined through stable ports and common policy boundaries.

```text
Contract v1 / Module SDK publication pipeline
                    |
                    | missing supported runtime bridge
                    v
Flow validation / FlowExecutorSaga / BlockRegistry
                    |
                    | incomplete universal proposal policy boundary
                    v
ActionRouter / Saga execution / external adapters
```

That gap is acceptable for the current Phase 1 contract work, but it blocks the deterministic M3 closed-loop proof and all later live or consequential behavior.

## 3. Current Readiness By Dimension

| Dimension | Current assessment | Readiness | Evidence class |
| --- | --- | --- | --- |
| Product and scope governance | Clear Active/Candidate distinction and promotion rules | Strong | Declared and Verified |
| Universal contracts | Shared primitives are merged; remaining six canonical contracts and deterministic policies are incomplete | In progress | Verified |
| Module authoring and publication | Contract v1, SDK, sandbox, evidence, lifecycle and publication controls are mature | Strong | Declared, Observed and Verified |
| Flow safety | Cycle rejection is fail-closed and protected by focused tests | Strong baseline | Verified |
| SDK module execution inside flows | Published SDK modules still lack a supported execution port into `FlowExecutorSaga` | Blocking for M3 | Observed and Inferred |
| Action proposal and policy | Runtime actions exist, but the universal `ActionProposal -> policy decision -> runtime action` boundary is incomplete | Blocking for real effects | Declared, Observed and Inferred |
| Durable confirmation and recovery | Saga mechanisms exist, but proposal-bound confirmation and exactly-once recovery remain remediation work | Blocking for consequential actions | Declared and Inferred |
| Persistence and migrations | SQLAlchemy, Alembic, PostgreSQL and repository patterns exist unevenly; universal ITO persistence is not yet designed | Not ready for M4 | Observed and Declared |
| Evidence sensitivity and retention | Generic artifacts exist, but universal sensitivity, retention, correction and tenant semantics are not enforced end to end | Not ready for private/live evidence | Declared and Inferred |
| Testing | Active and Candidate gates are explicit, deterministic and credential-free | Strong | Verified |
| Reviewer observability | Saga Console and run/artifact inspection provide a strong base, but ITO evidence and outcome views do not exist | Partial | Declared and Observed |
| Live source readiness | Fixture-first policy exists, but source contracts, replay, freshness, outage and prompt-injection isolation are not implemented for ITO | NO-GO | Declared |
| Consequential effects | Explicitly unauthorized in the Candidate phase | NO-GO | Declared |

## 4. Strengths To Preserve

### 4.1 Scope discipline

The repository does not pretend that every historical file is a supported product commitment. This is a major architectural strength because it prevents the broad legacy suite and old experiments from dictating new platform design.

Preserve:

- `SOURCE_OF_TRUTH.md` as canonical work policy;
- `docs/ACTIVE_PLATFORM_SCOPE.md` as the responsibility boundary;
- ADR-backed Candidate promotion;
- separate blocking gates for Active and Candidate surfaces.

### 4.2 Contract-first extension lifecycle

The Module SDK already covers validation, golden tests, sandboxing, qualification, evidence, lifecycle, repair, and human-gated publication. Future ITO verticals should be Contract v1 modules, not hard-coded branches in the platform core and not a second plugin system.

### 4.3 Deterministic development and review

Stub mode, fixture-first tests, a local portfolio launcher, and explicit gate inventories make the project reviewable without paid providers or production infrastructure. This is the correct basis for M1–M3.

### 4.4 Reliability mechanisms

The Saga layer already contains mechanisms for retry, idempotency, compensation, confirmation, timeout, persistence, locks, tracing, metrics, and dead-letter handling. The route should normalize access through stable ports rather than replace the Saga runtime.

### 4.5 Recent Candidate groundwork

Merged work has already established:

- ADR 0015 and Candidate packages;
- dependency-boundary tests;
- fail-closed flow cycle rejection;
- a separate Candidate quality gate;
- immutable shared primitives, enums, diagnostics, and schema snapshots.

This means `ITO-102` can remain a pure contract slice instead of reopening architecture or CI questions.

## 5. Critical Findings

### SYS-P0-001 — Published SDK modules cannot yet participate in the active flow runtime through a stable execution port

**Severity:** P0 for M3, not a blocker for ITO-102  
**Evidence:** Observed in the existing architecture audit; remediation remains unmerged.

Current behavior:

- Contract v1 supports a `module_sdk` execution adapter;
- the publication pipeline can validate and qualify an SDK package;
- active flows execute built-in blocks through `BlockRegistry` and `FlowExecutorSaga`;
- no canonical `ModuleExecutionPort` selects and invokes either built-in blocks or sandboxed SDK modules.

Risk:

- vertical modules may be duplicated as built-in blocks;
- sandbox and publication evidence may be bypassed;
- core runtime may accumulate vertical-specific execution branches.

Required route:

1. define a stable execution request/result/error port;
2. implement a built-in block adapter without behavior drift;
3. implement a sandboxed SDK adapter that consumes published evidence;
4. make `FlowContractValidator` and runtime resolve the same adapter semantics;
5. prove identical deterministic fixture behavior and failure isolation.

### SYS-P0-002 — The canonical semantic proposal and policy gateway is incomplete

**Severity:** P0 before any real financial, public, physical, or privacy-sensitive effect  
**Evidence:** Declared by the manifesto and audit; runtime mechanisms exist but are not yet unified.

The LLM or vertical module must produce a typed semantic `ActionProposal`, never a raw provider or actuator command. Before execution, a gateway must bind:

- tenant and user scope;
- declared capability;
- policy version and decision;
- confirmation class;
- cost or intensity ceiling;
- expiration;
- idempotency key;
- expected result and measurement plan;
- reversibility and compensation;
- audit evidence.

The current Candidate phase authorizes simulation only.

### SYS-P1-001 — Durable proposal confirmation and exactly-once recovery require explicit proof

**Severity:** P1 before bounded real action  
**Evidence:** Saga mechanisms are declared and partially observed; proposal-bound recovery is not yet verified.

A restart between confirmation, dispatch, and provider acknowledgement must not duplicate an effect or lose the user's decision. This requires a durable state machine and restart tests, not merely in-memory pending confirmation.

### SYS-P1-002 — Universal persistence, migrations, tenancy, and correction semantics are not yet defined

**Severity:** P1 before M4 and live evidence  
**Evidence:** Declared Candidate restriction and architecture audit.

Required foundations include:

- repository protocols above concrete SQLAlchemy/PostgreSQL adapters;
- explicit Alembic migrations;
- tenant- and user-scoped identities;
- immutable evidence with superseding corrections;
- append-only negative outcomes;
- retention, sensitivity, freshness, and deletion behavior;
- restart and rollback verification.

No table should be created during Phase 1 contract work.

### SYS-P1-003 — Artifact and evidence policy is not sufficient for sensitive or live observation

**Severity:** P1 before live/private sources  
**Evidence:** Existing artifact inspection is generic; ITO policy requires explicit sensitivity and retention.

The same evidence object must not be allowed to move from fixture replay to private user observation without an enforced storage policy, tenant scope, audit trail, and expiry behavior.

### SYS-P2-001 — Composition and code hotspots need exact inventory-backed ownership

**Severity:** P2  
**Evidence:** Inferred from the breadth of `app/main.py`, runtime wiring, API surface, and historical architecture; exact metrics pending the generated artifact.

The new analyzer will quantify:

- large Python and TypeScript files;
- route registrations and composition calls;
- import edges between API, services, domain, runtime, and infrastructure;
- broad catch and placeholder signals;
- configured boundary violations.

The result should drive small extraction tasks only where a target route needs them. A repository-wide cleanup is not part of M1–M3.

## 6. Immediate Checkpoint — ITO-102

`IntentContextV1` is **IMPLEMENTATION-READY** as a pure Candidate contract slice because its prerequisites are merged and it does not require the unresolved runtime, persistence, or external-effect work.

### Allowed scope

```text
app/contracts/opportunity/
tests/unit/opportunity/
tests/fixtures/opportunity/
schema snapshots and Candidate documentation when contract meaning changes
```

### Required invariants

- confirmed goals require explicit confirmation evidence;
- inferred interests remain distinct and cannot be promoted silently;
- tenant and user scope are mandatory;
- missing capability permission means deny;
- consequential capabilities are independently permissioned;
- financial execution defaults to denied and requires elevated or dual control;
- optimization targets are explicit;
- forbidden objectives take precedence over optimization;
- confirmation time and contract/policy version are recorded;
- unknown fields are rejected under the current compatibility policy;
- the model is immutable and domain-neutral.

### Required fixtures

1. valid retail intent;
2. unconfirmed inferred interest;
3. missing tenant/user scope;
4. consequential permission with insufficient confirmation;
5. optimization request conflicting with a forbidden transaction-count objective.

### Required proof

```bash
python -m pytest -q tests/unit/opportunity
python scripts/run_quality_gate.py intent-to-outcome
python scripts/run_quality_gate.py portfolio
```

The slice must not add API routes, service orchestration, persistence, live sources, module registration, UI, or any real effect.

## 7. Route To The Deterministic Closed Loop

```text
ANALYSIS-001  repeatable repository inventory and route protocol
      |
      v
ITO-102       IntentContextV1
      |
      v
ITO-103..108  evidence, hypothesis, opportunity, proposal, outcome,
             transition engine and deterministic policies
      |
      +------------------------------+
      |                              |
      v                              v
ITO-R003/R004 stable module          ActionProposal policy and
execution port + SDK adapter         simulation boundary remediation
      |                              |
      +---------------+--------------+
                      v
M2 fixture-only retail Contract v1 modules
                      |
                      v
M3 deterministic reference flow in stub mode
                      |
                      v
Saga Console evidence, proposal, simulated action and outcome inspection
```

### Route rules

- M1 contract tasks remain independent of FastAPI, persistence, providers, and UI.
- The execution bridge is preparatory platform work, not retail business logic.
- Action work stays simulated until a later ADR authorizes one bounded effect.
- Fixture modules must pass Contract v1 validation, golden tests, sandboxing, qualification, and human-gated publication evidence.
- M3 must run with deterministic fixtures and stub providers before live retail sources are considered.
- M4 persistence, M5 observation, M6 bounded action, M7 crypto research, and M8 sensors/devices remain separate gated programs.

## 8. GO / NO-GO Summary

| Gate | Current result | Explanation |
| --- | --- | --- |
| Analysis foundation | IN PROGRESS | Analyzer, profile, protocol, route template, tests and CI artifact are being introduced. |
| ITO-102 contract | GO after analysis PR is merged or independently based on clean main | Pure contract scope has merged prerequisites. |
| Complete M1 language | NO-GO | Remaining contracts, transitions and deterministic policies are missing. |
| M2 vertical modules | NO-GO | M1 exit gate is incomplete. |
| M3 closed loop | REMEDIATION-READY | Requires execution bridge, proposal simulation boundary and fixture modules. |
| Universal persistence | NO-GO | Repository protocols, migrations and tenancy semantics not designed. |
| Live retail sources | NO-GO | Replay, freshness, outage, authorization and injection isolation absent. |
| Real consequential action | NO-GO | No approved ADR, canonical proposal gateway, durable confirmation proof or bounded adapter. |
| Sensor/device work | NO-GO | Separate vertical ADR, simulator, threat model and permissions required. |
| Candidate promotion | NO-GO | Product responsibility and release evidence for the complete surface are not yet established. |

## 9. Next Required Evidence

The CI-generated `seed-system-analysis` artifact must be reviewed to replace qualitative hotspot and surface statements with exact metrics. The final deep-analysis report should then include:

- exact repository and language inventory;
- largest source and test hotspots;
- actual package dependency edges;
- route and composition-root counts;
- Pydantic model and protocol counts;
- environment-variable surface;
- declared Active/Candidate file distribution;
- configured dependency-boundary violations;
- workflow and quality-gate coverage;
- any mismatch between maintained scope and actual source paths.

## 10. Handoff

```json
{
  "audited_ref": "main@eee84040fd8388e842d45b1e099dcd898574fd01",
  "target_id": "SEED-ITO-M3",
  "readiness": "REMEDIATION-READY",
  "implementation_ready_checkpoint": "ITO-102",
  "p0_findings": [
    "missing SDK-module flow execution port",
    "incomplete canonical ActionProposal policy gateway"
  ],
  "p1_findings": [
    "durable confirmation and exactly-once recovery proof",
    "universal persistence and migration boundary",
    "sensitivity and retention-aware evidence storage"
  ],
  "required_gates": [
    "system-analysis workflow and artifact",
    "intent-to-outcome Candidate gate",
    "portfolio gate",
    "integration and demo smoke at later runtime slices"
  ],
  "consequential_effects_authorized": false,
  "next_recommended_slice": "merge ANALYSIS-001, then complete ITO-102 fixtures, tests, schema snapshot, Candidate gate and Cold Review"
}
```
