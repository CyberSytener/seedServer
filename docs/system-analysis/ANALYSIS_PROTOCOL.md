# Deep System Analysis Protocol

Status: preparatory analysis standard  
Owner: Seed Platform  
Applies to: repository-wide audits, major features, Candidate promotion, runtime remediation, persistence changes, live sources, and consequential actions

## 1. Objective

A deep analysis must answer three different questions without mixing them:

1. **What system exists now?**
2. **What does the maintained platform promise now?**
3. **What must change to reach a specific target safely?**

The result is not a generic code review. It is a traceable model of architecture, contracts, runtime composition, data, safety, verification, and delivery constraints.

## 2. Required Inputs

Every analysis freezes the following inputs before conclusions are written:

```text
repository
canonical branch
commit SHA
analysis profile version
target definition and target version
maintained source-of-truth documents
relevant ADRs
relevant PRs or unresolved review findings
available CI and test evidence
```

A report that does not name its audited ref is historical context, not a current assessment.

## 3. Evidence Classes

### Declared

A maintained source-of-truth document or accepted ADR explicitly states the claim.

Examples:

- a surface is Active or Candidate;
- a quality gate is mandatory;
- a capability is prohibited;
- a dependency direction is normative.

### Observed

Direct source inspection or the generated repository inventory shows the structure exists.

Examples:

- a router is registered;
- a class imports a concrete adapter;
- a table or migration exists;
- a workflow contains a specific command;
- a file is a hotspot.

### Verified

A focused test, CI workflow, smoke run, replay, or reproducible command demonstrates behavior.

Examples:

- a cycle is rejected before block creation;
- a Candidate gate passed on a named commit;
- an API returns a stable error contract;
- a restart test preserves idempotency.

### Inferred

A reasoned conclusion follows from Declared, Observed, or Verified evidence but has not been executed directly.

Every material inference must name:

- supporting evidence;
- confidence level;
- what would falsify it;
- the verification step required before implementation or promotion.

## 4. Analysis Stages

### Stage A — Freeze Scope

Record:

- canonical ref;
- target and non-goals;
- analysis surfaces;
- excluded archives, generated outputs, local data, and secrets;
- whether the analysis is read-only or may create preparatory infrastructure.

Stop when the target conflicts with an Active contract or silently promotes a Candidate surface.

### Stage B — Generate Static Inventory

Run:

```bash
python scripts/build_system_analysis.py --revision <ref>
```

Review at minimum:

- file and language distribution;
- largest Python and TypeScript files;
- package dependency edges;
- API route and composition signals;
- Pydantic models and protocol interfaces;
- environment-variable names;
- workflow and quality-gate inventories;
- declared-surface file coverage;
- configured dependency-boundary violations;
- parse errors, broad catches, placeholders, and TODO signals.

Static inventory is not runtime proof.

### Stage C — Map Runtime Composition

Trace each relevant path from entrypoint to effect:

```text
entrypoint
  -> router or command
  -> application service
  -> contract or domain model
  -> policy and authorization
  -> runtime executor
  -> infrastructure adapter
  -> persistence or external effect
  -> audit, telemetry, and user-visible result
```

For every composition root, record:

- where it is created;
- what concrete implementations are selected;
- how settings and secrets enter;
- how failure propagates;
- whether stub and production modes differ;
- whether lifecycle cleanup is defined.

### Stage D — Contract And State Analysis

For each target-relevant concept, inspect:

- input and output schemas;
- stable error codes;
- compatibility and versioning;
- lifecycle transitions;
- idempotency keys;
- confirmation and policy decisions;
- storage identity and tenant scope;
- expiry, freshness, retention, and sensitivity;
- negative and contradictory evidence;
- compensation or recovery semantics.

Free-form LLM prose does not count as an internal contract.

### Stage E — Safety And Authority Analysis

Identify every path capable of:

- spending or transferring value;
- publishing or messaging externally;
- changing prices or availability;
- accessing private or sensitive data;
- controlling devices or physical effects;
- granting permissions or publishing modules;
- bypassing confirmation, sandbox, policy, idempotency, or audit gates.

For each path, record:

```text
capability declaration
policy decision
confirmation class
cost or intensity ceiling
idempotency
expiration
expected result
measurement plan
compensation or recovery
audit evidence
```

Missing authority defaults to deny.

### Stage F — Verification Map

Map claims to the narrowest available proof:

| Claim type | Preferred proof |
| --- | --- |
| pure contract invariant | focused unit and schema snapshot test |
| dependency boundary | AST or import-boundary test |
| application orchestration | integration test with deterministic adapters |
| restart and recovery | persistence/restart integration test |
| API compatibility | contract and response fixture test |
| live source behavior | sanitized replay plus conditional smoke |
| external effect | simulator, policy denial, confirmation, idempotency, and compensation tests |
| reviewer journey | portfolio demo smoke and UI build |

A broad green suite cannot replace a missing focused test for a critical boundary.

### Stage G — Gap And Risk Model

Each finding uses:

```json
{
  "finding_id": "AREA-NNN",
  "title": "",
  "severity": "P0|P1|P2|P3",
  "evidence_class": "declared|observed|verified|inferred",
  "affected_paths": [],
  "current_behavior": "",
  "target_behavior": "",
  "risk": "",
  "required_proof": "",
  "recommended_slice": ""
}
```

Severity definitions:

- **P0** — direct safety bypass, data corruption risk, or blocker for the target architecture.
- **P1** — required before persistence, live sources, Candidate promotion, or consequential effects.
- **P2** — significant maintainability, operability, or correctness debt.
- **P3** — improvement that does not block the target route.

### Stage H — Build The Route

Use `TASK_ROUTE_TEMPLATE.md`.

The route must:

- start from the audited canonical ref;
- name prerequisites and blocked work;
- separate preparatory remediation from product behavior;
- preserve Active surfaces and deterministic stub mode;
- define one reviewable outcome per slice;
- identify contracts, paths, tests, gates, migration, rollback, and observability;
- stop before live sources or consequential effects when their GO gate is not satisfied.

## 5. System Dimensions

Every deep analysis rates the following dimensions separately:

| Dimension | Core question |
| --- | --- |
| Product and scope | Is the responsibility Active, Candidate, Experimental, or historical? |
| Contracts | Are inputs, outputs, errors, versions, and compatibility explicit? |
| Architecture | Do dependencies and ownership boundaries match the declared design? |
| Runtime | How are components composed, executed, retried, stopped, and recovered? |
| Data | Are identity, tenancy, migrations, retention, freshness, and correction semantics defined? |
| Safety and policy | Can authority, confirmation, capabilities, secrets, or external effects be bypassed? |
| Testing | Which exact behavior is release-blocking and which is only diagnostic? |
| Observability | Can an operator explain what happened and why? |
| Operability | Can the system start, degrade, recover, and roll back predictably? |
| Delivery | Can the target be reached through small branches with explicit exit gates? |

Scores are supporting summaries, not evidence. A high average cannot cancel a P0 finding.

## 6. Readiness Labels

- **NO-GO** — a P0 exists or target authority is not approved.
- **REMEDIATION-READY** — blockers are understood and can be removed through preparatory slices.
- **IMPLEMENTATION-READY** — contracts, boundaries, tests, and rollback are sufficient for the next slice.
- **VERIFICATION-READY** — implementation exists and awaits declared focused proof.
- **PROMOTION-READY** — Candidate responsibility, ownership, failure behavior, ADR, and release-blocking evidence are complete.

## 7. Cold Review

Before a route is marked IMPLEMENTATION-READY, an independent read-only review must attack:

- unsupported claims;
- missed composition roots;
- hidden direct imports;
- accidental Candidate-to-Active promotion;
- unbounded authority or external effects;
- missing invalid, stale, contradictory, adversarial, restart, and recovery cases;
- migration and rollback omissions;
- tests that prove less than their names suggest;
- roadmap steps that are too broad for one PR.

The reviewer reports `approve`, `request_changes`, or `block`. The reviewer does not edit code or self-approve publication.

## 8. Analysis Handoff

Every completed analysis returns:

```json
{
  "audited_ref": "",
  "target_id": "",
  "readiness": "NO-GO|REMEDIATION-READY|IMPLEMENTATION-READY|VERIFICATION-READY|PROMOTION-READY",
  "declared_facts": [],
  "observed_facts": [],
  "verified_facts": [],
  "inferences": [],
  "p0_findings": [],
  "p1_findings": [],
  "unknowns": [],
  "route_slices": [],
  "required_gates": [],
  "next_recommended_slice": ""
}
```

Do not claim runtime verification when only source inspection or static inventory was available.
