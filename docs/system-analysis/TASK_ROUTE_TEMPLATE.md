# Target Route Template

Use this template after the static inventory and manual architecture analysis are complete. A route is an execution contract for maintainers; it is not a wishlist.

# 1. Route Metadata

```yaml
target_id:
target_version:
audited_repository:
audited_ref:
analysis_profile_version:
route_status: draft|cold-reviewed|approved|superseded
readiness: NO-GO|REMEDIATION-READY|IMPLEMENTATION-READY|VERIFICATION-READY|PROMOTION-READY
owner:
created_at:
```

# 2. Target Definition

## Goal

State one externally understandable result.

## Immediate checkpoint

Name the next reviewable outcome, not the entire strategic vision.

## Success evidence

List the exact artifacts, contracts, test outputs, UI evidence, or runtime observations that prove success.

## Non-goals

Explicitly exclude adjacent cleanup, live integrations, unrelated verticals, production deployment, and consequential actions unless they are part of the approved target.

## Authority boundary

State what the implementation is permitted to propose, simulate, persist, publish, or execute. Missing authority defaults to deny.

# 3. Frozen Starting Point

| Item | Value | Evidence class |
| --- | --- | --- |
| Canonical commit |  | Verified |
| Active platform scope |  | Declared |
| Candidate/Experimental status |  | Declared |
| Relevant merged prerequisites |  | Verified |
| Open or unmerged branches |  | Observed |
| Required quality gates |  | Declared and Verified |
| Known P0/P1 findings |  | Observed/Verified/Inferred |

# 4. Current-System Trace

Trace the target through the current system:

```text
user or external input
  -> API / CLI / module entrypoint
  -> application service
  -> universal and vertical contracts
  -> policy / authorization / confirmation
  -> runtime execution
  -> infrastructure and persistence
  -> audit / telemetry / operator UI
  -> measured outcome
```

For every arrow, record:

- current concrete path;
- intended stable interface;
- whether the link exists;
- whether it is Active, Candidate, Experimental, or missing;
- failure behavior;
- exact evidence.

# 5. Affected Surface Matrix

| Surface | Status | Paths | Contracts | Current proof | Required proof | Change allowed? |
| --- | --- | --- | --- | --- | --- | --- |
| API / Console |  |  |  |  |  | yes/no |
| Application services |  |  |  |  |  | yes/no |
| Universal contracts |  |  |  |  |  | yes/no |
| Vertical module |  |  |  |  |  | yes/no |
| Flow / Saga runtime |  |  |  |  |  | yes/no |
| Action policy |  |  |  |  |  | yes/no |
| Persistence |  |  |  |  |  | yes/no |
| External source/effect |  |  |  |  |  | yes/no |
| Tests / CI |  |  |  |  |  | yes/no |
| Documentation / ADR |  |  |  |  |  | yes/no |

# 6. Findings And Gaps

Use one entry per independently actionable finding.

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
  "falsification_or_verification": "",
  "recommended_slice": ""
}
```

Do not combine several unrelated risks under one finding merely to reduce the count.

# 7. Dependency Graph

Express task dependencies explicitly:

```text
PREP-001 ─┬─> CONTRACT-001 ─> POLICY-001 ─> SERVICE-001
          └─> RUNTIME-001  ────────────────────────┘

SERVICE-001 + FIXTURE-001 -> E2E-001 -> PROMOTION-GATE
```

Rules:

- product behavior cannot depend on an unmerged preparatory branch;
- a later slice cannot begin while a prerequisite GO gate is red;
- migration, rollback, and observability work are dependencies, not post-release notes;
- live sources and consequential effects remain blocked until fixture replay and policy gates are green.

# 8. Route Slices

Repeat this section for each PR-sized slice.

## `<SLICE-ID>` — `<title>`

### Purpose

One reviewable outcome.

### Entry conditions

- merged prerequisites;
- required ADR status;
- required fixtures or contracts;
- current canonical ref is green.

### Scope

```text
paths allowed to change
contracts added or changed
runtime behavior added or changed
data or migration effects
operator or UI behavior
```

### Non-goals

List work that must remain outside this slice.

### Invariants

State deterministic safety and compatibility rules.

### Failure behavior

Define errors, timeouts, denied behavior, stale data, partial failure, recovery, and cleanup.

### Fixtures and tests

```text
valid
invalid
missing permission
stale
contradictory
adversarial
idempotency
restart/recovery
compensation
schema snapshot
```

Use only cases relevant to the slice, but never omit safe failure paths.

### Required gates

```bash
focused command
Candidate or portfolio gate
integration gate when applicable
smoke or UI build when applicable
conditional provider or deployment evidence only when authorized
```

### Rollout

- feature flag or registration boundary;
- default mode;
- canary or simulation path;
- metrics and audit events;
- rollback trigger.

### Exit criteria

Describe evidence required for `VERIFIED` and `COLD_REVIEWED`.

# 9. GO / NO-GO Gates

| Gate | GO criteria | NO-GO condition | Evidence |
| --- | --- | --- | --- |
| Contract | Stable schemas, diagnostics, compatibility and fixtures | contract meaning remains implicit |  |
| Architecture | Dependency direction and ownership are explicit | direct infrastructure or composition bypass |  |
| Runtime | deterministic execution and failure semantics | hidden fallback or partial side effect |  |
| Data | identity, tenant, migration, retention and correction defined | ad-hoc table or mutable evidence |  |
| Policy | capability, confirmation, cost, expiry and authority enforced | LLM/raw input reaches actuator directly |  |
| Verification | focused failure and recovery tests pass | only broad suite or manual happy path |  |
| Observability | operator can explain decision and effect | action cannot be reconstructed |  |
| Promotion | owner, ADR, failure policy and blocking tests exist | Candidate is used as Active without promotion |  |

# 10. Verification Matrix

| Claim | Evidence needed | Command/workflow | Artifact | Blocking? |
| --- | --- | --- | --- | --- |
|  |  |  |  | yes/no |

A claim cannot be marked Verified merely because a neighboring workflow passed.

# 11. Migration, Rollback, And Recovery

Describe:

- schema migration and backfill;
- compatibility window;
- rollback without data loss;
- feature disable behavior;
- pending work and inflight Saga handling;
- idempotency after retry or rollback;
- artifact retention and audit preservation.

Use `not applicable` with a reason rather than leaving the section blank.

# 12. Observability Plan

Record:

- structured events;
- trace and correlation IDs;
- metrics and thresholds;
- dashboards or Console views;
- alert conditions;
- evidence needed to diagnose an incorrect proposal, denied action, partial failure, or bad outcome.

# 13. Unknowns And Decisions

| Unknown | Why it matters | Resolution method | Blocks slice |
| --- | --- | --- | --- |
|  |  |  | yes/no |

Unknown source authorization, consequential-action policy, data retention, or migration ownership blocks implementation rather than becoming an assumption.

# 14. Cold Review Result

```json
{
  "review_result": "approve|request_changes|block",
  "scope_compliance": [],
  "contract_risks": [],
  "security_risks": [],
  "test_gaps": [],
  "hidden_coupling": [],
  "unsupported_claims": [],
  "required_changes": []
}
```

# 15. Route Handoff

```json
{
  "audited_ref": "",
  "target_id": "",
  "readiness": "",
  "route_slices": [],
  "blocked_slices": [],
  "required_gates": [],
  "migration_required": false,
  "consequential_effects_authorized": false,
  "risks_remaining": [],
  "next_recommended_slice": ""
}
```
