# Seed Intent-to-Outcome Implementation Plan

Status: Candidate execution plan  
Owner: Seed Platform  
Last updated: 2026-07-17  
Applies to: `CyberSytener/seedServer`  
Normative architecture: `docs/INTENT_TO_OUTCOME_MANIFEST.md`

## 1. Purpose

This document converts the Intent-to-Outcome manifesto into an ordered, reviewable implementation program for Codex and human maintainers.

The target loop is:

```text
UNDERSTAND -> OBSERVE -> DISCOVER -> VERIFY -> PLAN -> ACT -> MEASURE -> LEARN
```

The plan must be executed as small, evidence-backed pull requests. A later stage must not begin merely because code for an earlier stage exists. It begins only after the earlier stage satisfies its exit gate.

The first product proof is a deterministic retail-footwear scenario. Live sources, real spending, crypto order execution, sensor access, and physical actions are not part of the first milestone.

## 2. Program Rules

### 2.1 Source of truth

Before starting any task, read:

1. `SOURCE_OF_TRUTH.md`;
2. `docs/ACTIVE_PLATFORM_SCOPE.md`;
3. `docs/PLATFORM_ROADMAP.md`;
4. `docs/MODULE_CONTRACT_V1.md`;
5. `docs/MODULE_SDK.md`;
6. `docs/TEST_STRATEGY.md`;
7. `docs/INTENT_TO_OUTCOME_MANIFEST.md`;
8. this implementation plan;
9. `AGENTS.md`;
10. relevant ADRs.

This plan is subordinate to active platform contracts. A task that conflicts with an active contract must stop and produce an ADR or a smaller preparatory task.

### 2.2 One task, one branch, one reviewable outcome

Each task uses:

```text
branch: agent/ito-<task-id>-<short-name>
commit: focused and descriptive
PR: one task or one tightly coupled vertical slice
```

Do not combine unrelated cleanup, architecture refactors, UI polish, live integrations, and business behavior in one PR.

### 2.3 Required task states

Every task moves through:

```text
PLANNED -> IN_PROGRESS -> IMPLEMENTED -> VERIFIED -> COLD_REVIEWED -> MERGED
```

A task may also be:

```text
BLOCKED
REJECTED
SUPERSEDED
```

`IMPLEMENTED` means code or documentation exists.  
`VERIFIED` means declared tests and gates passed.  
`COLD_REVIEWED` means an independent read-only review attacked the result rather than defending it.  
Only `COLD_REVIEWED` work is merge-ready.

### 2.4 Required handoff envelope

Every Codex task must return:

```json
{
  "task_id": "ITO-XXX",
  "phase": "phase_name",
  "state": "IMPLEMENTED|VERIFIED|BLOCKED",
  "scope_completed": [],
  "files_changed": [],
  "contracts_changed": [],
  "tests_added_or_run": [],
  "quality_gates": [],
  "risks_remaining": [],
  "manifest_deviations": [],
  "next_recommended_slice": ""
}
```

Do not report a test as executed when it was only inspected or inferred.

### 2.5 Cold Review protocol

After implementation and focused verification, a Reviewer Agent receives:

- the assigned task text;
- the relevant manifest sections;
- the diff;
- test output;
- the handoff envelope.

The Reviewer Agent must not edit code. It must report:

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

The implementation agent may address the findings in the same task branch. Publication or lifecycle approval remains human-gated.

## 3. Milestone Map

| Milestone | Goal | Included phases | Completion proof |
| --- | --- | --- | --- |
| M0 — Boundary | Establish Candidate scope and package boundaries | Phase 0 | ADR accepted, no runtime behavior |
| M1 — Language | Define universal typed contracts and deterministic policies | Phase 1 | schemas, transitions, scoring tests green |
| M2 — Modules | Implement fixture-only Contract v1 modules | Phase 2 | CLI validation, golden tests, sandbox evidence |
| M3 — Closed Loop | Demonstrate retail Intent-to-Outcome in stub mode | Phase 3 | deterministic end-to-end demo and Console evidence |
| M4 — Memory | Persist intents, evidence, hypotheses, proposals, and outcomes | Phase 4 | restart-safe, tenant-scoped history |
| M5 — Observation | Add controlled live retail sources | Phase 5 | replayable adapters, freshness and outage handling |
| M6 — Bounded Action | Integrate one confirmation-gated action draft | Phase 6 | no-spend default, idempotency and recovery tests |
| M7 — Second Vertical | Prove reuse with read-only crypto research | Phase 7 | no trading capabilities, provenance-aware reports |
| M8 — World Interfaces | Add sensor/device verticals independently | Phase 8 | per-pack ADR, simulator, threat model, permissions |

Milestones M0–M3 form the first implementation program. M4–M8 must not distract from completing the deterministic closed-loop proof.

# 4. Phase 0 — Decision and Boundary

## Phase objective

Turn the manifesto into an accepted Candidate platform boundary without introducing runtime behavior.

## Entry conditions

- current `main` is clean and demoable;
- manifesto and `AGENTS.md` are reviewed;
- existing Active surfaces are understood;
- no assumption is made that Candidate agent, provider, or persistence code is already supported.

## ITO-001 — Candidate-surface ADR

### Goal

Create an ADR that declares Intent-to-Outcome a Candidate surface and names the ownership, dependency direction, non-goals, promotion requirements, and rollback strategy.

### Required files

```text
docs/adr/NNNN-intent-to-outcome-candidate-surface.md
```

### Required decisions

- universal platform concepts are limited to intent, evidence, hypothesis, opportunity, action proposal, and outcome;
- retail, crypto, sensors, public observation, Home, and Companion remain vertical packs;
- existing Module Contract, SDK, Saga runtime, ActionRouter, sandbox, and publication gates are reused;
- the existing `market_scanner` remains job-specific;
- no live sources or real consequential actions are authorized;
- Candidate-to-Active promotion requires focused release-blocking tests and a later ADR.

### Tests and gates

```bash
python scripts/run_quality_gate.py portfolio
```

### Exit criteria

- ADR status is accepted or explicitly proposed for review;
- no runtime or module behavior is changed;
- active-scope documentation remains internally consistent.

## ITO-002 — Package and test skeleton

### Goal

Create empty architectural package boundaries and focused test directories without implementing domain behavior.

### Target paths

```text
app/contracts/opportunity/
app/domain/opportunity/
app/services/opportunity/
tests/unit/opportunity/
tests/integration/opportunity/
tests/fixtures/opportunity/
```

### Rules

- package files may contain exports and documentation only;
- no `pass` placeholders in claimed-complete production classes;
- no API route;
- no database table;
- no provider dependency;
- no changes to `app/main.py`;
- no new runtime registration.

### Required verification

- Python imports succeed;
- dependency-direction smoke tests prove the domain package does not import FastAPI, Redis, concrete databases, providers, or UI code;
- portfolio gate remains green.

### Exit criteria

- the package boundary exists;
- test collection succeeds;
- the next task can add contracts without moving directories again.

## Phase 0 gate

Phase 1 may start only when:

- ITO-001 and ITO-002 are merged;
- no runtime behavior was introduced accidentally;
- Cold Review finds no conflict with Active scope;
- exact canonical class names are accepted.

# 5. Phase 1 — Universal Contracts and Deterministic Policies

## Phase objective

Create the stable internal language used by every future vertical.

No module, API, database, live source, or UI work belongs in this phase.

## ITO-101 — Shared primitives

### Goal

Implement reusable value objects and enums needed by the six canonical contracts.

### Candidate primitives

- bounded confidence value `[0.0, 1.0]`;
- source and ingestion timestamps;
- sensitivity class;
- retention class;
- provenance step;
- evidence relation type;
- confirmation class;
- reversibility class;
- monetary amount in integer minor units;
- policy version reference;
- lifecycle status enums.

### Required behavior

- timezone-aware timestamps only;
- no floating-point money;
- confidence outside `[0,1]` fails with a stable diagnostic;
- enum serialization is stable;
- unknown future fields follow an explicitly documented compatibility policy.

### Tests

- valid serialization round trip;
- invalid confidence;
- naive timestamp rejection;
- negative or malformed monetary values where forbidden;
- schema snapshot stability.

## ITO-102 — `IntentContextV1`

### Goal

Represent confirmed goals, constraints, preferences, permissions, optimization targets, and forbidden objectives.

### Required invariants

- inferred interests cannot become confirmed goals silently;
- consequential capabilities are independently permissioned;
- `execute_financial_actions` defaults to false;
- optimization targets and forbidden objectives are explicit;
- the model records confirmation time and version.

### Fixtures

- valid retail intent;
- unconfirmed inferred interest;
- missing user/tenant scope;
- conflicting permission and confirmation requirements;
- forbidden objective attempting to maximize transaction count.

## ITO-103 — `EvidenceItemV1`

### Goal

Represent immutable observations and their provenance.

### Required invariants

- observation and ingestion times are distinct;
- source reference and transformation chain are present;
- sensitivity and retention are explicit;
- support and contradiction links reference stable evidence IDs;
- corrections create a superseding item rather than mutating the old record.

### Fixtures

- direct measurement;
- normalized review claim;
- stale price observation;
- contradictory quality report;
- corrected evidence item;
- missing provenance;
- impossible timestamp ordering.

## ITO-104 — `HypothesisV1`

### Goal

Represent falsifiable statements linked to supporting and contradicting evidence.

### Required invariants

- a hypothesis eligible for opportunity ranking has linked evidence;
- expected observations and weakening observations are present;
- assumptions and known confounders are explicit;
- lifecycle transitions are not arbitrary.

### Allowed lifecycle

```text
proposed -> testing -> supported
                    -> weakened
                    -> rejected
proposed -> expired
testing  -> expired
supported|weakened -> expired
```

Any additional transition requires an ADR or explicit contract amendment.

## ITO-105 — `OpportunityV1`

### Goal

Represent an evaluated hypothesis in relation to a confirmed intent.

### Required invariants

- expected value is a range, not a fabricated scalar;
- downside, cost, reversibility, horizon, uncertainty, and freshness are explicit;
- score components identify their policy version;
- the smallest useful experiment is linked or described;
- expired evidence cannot receive a freshness-perfect score.

## ITO-106 — `ActionProposalV1`

### Goal

Represent a semantic proposal that cannot execute itself.

### Required invariants

- requested capabilities are explicit;
- confirmation class is explicit;
- idempotency key and expiry are required for consequential proposals;
- cost ceiling or maximum loss is present where applicable;
- expected result and measurement plan are required;
- compensation or recovery behavior is declared;
- the contract contains no raw provider command, exchange order, actuator pulse, or private credential.

## ITO-107 — `OutcomeRecordV1`

### Goal

Compare predicted and observed results without discarding failures.

### Required invariants

- prediction range and observation window are recorded;
- costs, side effects, and user intervention are preserved;
- attribution confidence is explicit;
- negative outcomes remain queryable;
- preference updates are proposals requiring policy approval, not automatic mutations.

## ITO-108 — Transition policy engine

### Goal

Implement pure deterministic transition functions for hypothesis, opportunity, and action-proposal lifecycle.

### Rules

- transition code belongs in `app/domain/opportunity/`;
- models do not contain service or infrastructure logic;
- invalid transitions return stable machine-readable diagnostics;
- transition functions are side-effect free.

### Required tests

- every allowed transition;
- every prohibited transition from terminal states;
- expiry behavior;
- repeated transition idempotency where intended;
- high-impact proposal cannot become execution-ready without policy and confirmation evidence.

## ITO-109 — Deterministic opportunity scoring v1

### Goal

Rank opportunities using visible, policy-versioned components.

### Initial score components

```text
goal_alignment
support_strength
contradiction_penalty
source_diversity
freshness
expected_value
cost_penalty
downside_penalty
reversibility
uncertainty_penalty
```

### Rules

- LLM prose may explain a score but cannot calculate the hidden final score;
- weights and normalization are versioned;
- each component is returned to the caller;
- missing evidence reduces confidence rather than receiving a neutral hidden default;
- high contradiction or stale evidence can trigger `insufficient_evidence` rather than a low but actionable score.

### Required test families

- deterministic repeatability;
- monotonicity for stronger support and higher contradiction;
- freshness degradation;
- source-concentration penalty;
- cost/downside sensitivity;
- high expected value cannot override forbidden permissions;
- score explanation matches actual components.

## Phase 1 gate

Phase 2 may start only when:

```bash
python -m pytest -q tests/unit/opportunity
python scripts/run_quality_gate.py portfolio
```

and all of the following are true:

- all six contracts have versioned Pydantic models and portable JSON Schemas;
- valid, invalid, stale, contradictory, and high-risk fixtures exist;
- contract tests have no provider, API, UI, Redis, or database dependency;
- scoring and transitions are deterministic;
- Cold Review finds no retail-, crypto-, sensor-, or Companion-specific fields in universal contracts.

# 6. Phase 2 — Fixture-Only Contract v1 Modules

## Phase objective

Implement the loop as small Contract v1 modules using deterministic fixtures and the stable Module SDK.

All modules remain draft Candidate packages until lifecycle evidence and human approval are provided.

## Module implementation order

```text
intent_context_builder
retail_catalog_snapshot
retail_competitor_price_observer
retail_review_signal_extractor
retail_supplier_snapshot
retail_unit_economics
evidence_synthesizer
hypothesis_builder
evidence_critic
opportunity_ranker
experiment_planner
outcome_reviewer
```

## ITO-201 — `intent_context_builder`

### Input

Explicit user-provided retail goal, constraints, preferences, and permissions.

### Output

Draft `IntentContextV1` with unconfirmed fields clearly marked.

### Non-goals

- no browsing;
- no inferred-sensitive traits;
- no persistence;
- no execution.

### Required evidence

```bash
seed module validate intent_context_builder
seed module test intent_context_builder
seed module sandbox intent_context_builder
```

## ITO-202 — Retail snapshot modules

### Goal

Create fixture-only observers for catalog, competitor prices, reviews, suppliers, and unit economics.

### Rules

- no network access;
- fixture paths are declared and sandbox-compatible;
- every observation includes provenance and timestamps;
- fixture clocks are controllable for freshness tests;
- raw untrusted text is represented as data, never injected as instructions.

### Required fixtures

1. baseline stable market;
2. waterproof urban sneaker demand signal;
3. contradictory quality complaints;
4. stale competitor prices;
5. unavailable supplier;
6. concentrated review source;
7. negative unit economics;
8. malformed or prompt-injected review text.

## ITO-203 — `evidence_synthesizer`

### Goal

Normalize fixture observations into immutable `EvidenceItemV1` records.

### Required behavior

- deterministic deduplication;
- provenance chain preservation;
- support/contradiction relationship creation;
- no arbitrary source fetching;
- explicit diagnostics for malformed observations.

## ITO-204 — `hypothesis_builder`

### Goal

Create falsifiable hypotheses from normalized evidence.

### Required output

- statement;
- supporting and contradicting evidence IDs;
- confounders;
- expected observations if true;
- weakening observations;
- confidence basis.

The module may use a stub LLM path for deterministic output, but its contract and golden cases must not depend on a paid provider.

## ITO-205 — `evidence_critic`

### Goal

Attack hypotheses independently.

### Independence requirements

- separate prompt/rubric version from `hypothesis_builder`;
- receives original evidence rather than only the builder's summary;
- must be able to lower confidence, add confounders, or recommend rejection;
- may not rewrite evidence to make a preferred conclusion stronger.

### Adversarial tests

- social-source echo chamber;
- duplicated claims presented as independent sources;
- stale price spike;
- seasonal confounder;
- prompt injection in review text;
- strong demand with unacceptable supplier quality.

## ITO-206 — `opportunity_ranker`

### Goal

Apply deterministic scoring v1 to hypotheses and confirmed intent.

### Required behavior

- reject unconfirmed consequential intent;
- expose every score component;
- preserve contradiction evidence in output;
- return `insufficient_evidence` where policy requires it;
- no hidden prompt-only ranking.

## ITO-207 — `experiment_planner`

### Goal

Propose the smallest reversible experiment that reduces uncertainty.

### Reference result

For the retail fixture, prefer samples and a 20-unit simulated test over a large purchase.

### Required behavior

- output only `ActionProposalV1`;
- require confirmation;
- declare cost ceiling, expiry, idempotency, reversibility, and measurement plan;
- no direct supplier call or order placement.

## ITO-208 — `outcome_reviewer`

### Goal

Compare a simulated outcome with the prediction.

### Required behavior

- preserve failed experiments;
- distinguish observed result from causal attribution;
- update hypothesis status only through transition policy;
- propose, but not automatically apply, preference changes;
- emit calibration information.

## ITO-209 — Module edge compatibility suite

### Goal

Validate every intended connection before flow execution.

### Required edge matrix

| Producer | Consumer |
| --- | --- |
| intent builder | opportunity ranker / experiment planner |
| retail observers | evidence synthesizer |
| evidence synthesizer | hypothesis builder |
| evidence synthesizer | evidence critic |
| hypothesis builder | evidence critic |
| hypothesis builder + critic | opportunity ranker |
| opportunity ranker | experiment planner |
| experiment planner + simulated outcome | outcome reviewer |

Every incompatible schema mutation must fail before runtime.

## Phase 2 gate

Phase 3 may start only when:

- every module validates through Contract v1;
- golden tests pass;
- subprocess sandbox evidence is clean;
- declared capabilities match observed behavior;
- no module accesses network, arbitrary filesystem, process APIs, secrets, `app.state`, or concrete infrastructure;
- compatibility tests cover every flow edge;
- portfolio gate remains green;
- Cold Review confirms that no single module has become a hidden super-agent.

# 7. Phase 3 — Deterministic Retail Reference Flow

## Phase objective

Prove the complete reusable loop in the Saga Console without credentials, live sources, or real spending.

## ITO-301 — Reference flow contract

### Goal

Define a Gallery flow connecting the Phase 2 modules.

### Canonical flow

```text
confirmed retail intent
  -> fixture observers
  -> evidence synthesizer
  -> hypothesis builder
  -> evidence critic
  -> opportunity ranker
  -> experiment planner
  -> simulated confirmation
  -> simulated test action
  -> outcome reviewer
```

### Requirements

- explicit field mappings on every edge;
- compile, validate, sandbox, and run gates use existing flow infrastructure;
- flow ID is new and stable;
- existing job-market Gallery flow is unchanged.

## ITO-302 — Simulated action and confirmation

### Goal

Exercise ActionRouter and Saga confirmation behavior without a real external side effect.

### Required states

```text
PROPOSED -> WAITING_CONFIRMATION -> CONFIRMED -> SIMULATED_EXECUTION -> COMPLETED
                                 -> REJECTED
                                 -> EXPIRED
                                 -> FAILED -> RECOVERY_RECORDED
```

### Tests

- execution denied without confirmation;
- duplicate confirmation is idempotent;
- expired proposal cannot execute;
- cost ceiling is preserved;
- simulated adapter failure produces explainable state;
- retry does not duplicate simulated order;
- recovery and audit records exist.

## ITO-303 — Evidence artifacts and run timeline

### Goal

Expose the complete reconstructable chain in run artifacts.

The operator must be able to inspect:

- confirmed intent;
- raw fixture observation references;
- normalized evidence;
- supporting and contradicting evidence;
- hypothesis and confounders;
- visible score components;
- bounded proposal and confirmation state;
- simulated result;
- outcome review and calibration.

## ITO-304 — Saga Console Candidate views

### Goal

Add the minimum UI required to understand the reference flow.

### Required UI

- Candidate status label;
- opportunity summary;
- evidence support/contradiction lists;
- score-component breakdown;
- action proposal with cost/expiry/confirmation class;
- outcome comparison;
- clear simulated-data indicator.

### Non-goals

- consumer-facing storefront;
- generalized dashboard builder;
- live charts;
- crypto UI;
- autonomous control UI;
- visual redesign unrelated to the reference scenario.

## ITO-305 — Deterministic end-to-end acceptance test

### Goal

Prove the first milestone with one command.

### Acceptance story

1. load a confirmed goal to improve margin without stale inventory;
2. ingest fixture observations;
3. normalize evidence with provenance;
4. form a waterproof-urban-sneaker demand hypothesis;
5. display contradictory quality evidence;
6. rank the opportunity using visible deterministic components;
7. propose samples plus a 20-unit simulated test;
8. deny execution before confirmation;
9. confirm and run the simulated action;
10. record a simulated sell-through result;
11. explain whether the hypothesis was supported and what remains uncertain.

### Required commands

```bash
python -m pytest -q tests/unit/opportunity
python -m pytest -q tests/integration/opportunity
python scripts/run_quality_gate.py portfolio
python scripts/run_quality_gate.py integration
python scripts/run_portfolio_demo.py --smoke-test --no-open
cd saga-console && npm run build
```

A dedicated command may be added, for example:

```bash
python scripts/run_intent_to_outcome_demo.py --smoke-test --no-open
```

It must not replace existing portfolio verification.

## Phase 3 gate — First milestone complete

M3 is complete only when:

- a clean clone can run the reference story without external credentials;
- the result is deterministic under a fixed fixture clock and seed;
- support and contradiction evidence are inspectable;
- no consequential action runs without confirmation;
- failures and negative outcomes remain visible;
- existing portfolio demo remains green;
- Saga Console builds;
- Cold Review approves contract adherence, safety, and reproducibility.

# 8. Phase 4 — Persistence and Outcome Learning

Phase 4 begins only after the closed-loop demo is stable.

## ITO-401 — Repository protocols

Define protocols for:

- intents;
- evidence;
- hypotheses;
- opportunities;
- action proposals;
- outcomes;
- calibration summaries.

Protocols belong above infrastructure and contain no SQL or FastAPI imports.

## ITO-402 — SQLite development adapter

Add explicit migrations and a development adapter.

### Required properties

- tenant/user scoping;
- append-only evidence and outcome history;
- supersession instead of destructive correction;
- explicit created/observed/ingested timestamps;
- queryable negative outcomes;
- reversible development migrations.

## ITO-403 — Persistence service integration

Application services coordinate repositories and transition policies. Modules continue to use stable SDK contracts and must not access the database directly.

## ITO-404 — Correction, export, and deletion controls

Provide user-visible or operator-visible controls for:

- correcting confirmed intent;
- superseding evidence;
- exporting records;
- deleting or anonymizing data according to retention policy;
- reversing proposed preference updates.

## ITO-405 — Calibration reports

Measure:

- prediction interval coverage;
- confidence calibration;
- source reliability by domain and version;
- false-positive opportunity rate;
- experiment success and failure preservation.

Do not optimize by hiding rejected hypotheses or failed experiments.

## Phase 4 gate

- records survive restart;
- tenant isolation tests pass;
- corrections preserve history;
- deletion/retention behavior is documented and tested;
- preference updates remain policy-gated and reversible;
- the deterministic fixture demo can replay from persisted records.

# 9. Phase 5 — Controlled Live Retail Sources

## Authorization gate

A live adapter task must not start until the source's authorization, intended use, terms, rate limits, data retention, and secret handling are documented.

## ITO-501 — Source adapter contract

Define a shared adapter result containing:

- source ID and authorized use;
- observation time;
- retrieval time;
- provenance;
- freshness window;
- cache metadata;
- rate-limit state;
- health state;
- sensitivity and retention;
- sanitized replay fixture reference.

## ITO-502 — First price/catalog adapter

Implement one authorized source behind a feature flag.

### Required behavior

- live mode can be disabled completely;
- unavailable source becomes explicit evidence or error;
- stale data reduces confidence;
- secrets come from a brokered reference and never enter module prompts or logs;
- recorded sanitized fixtures reproduce integration tests.

## ITO-503 — First review/trend adapter

Apply strict untrusted-text isolation.

### Required behavior

- source content is data, not instructions;
- prompt-injection markers are tested;
- source concentration is measurable;
- transformations preserve provenance;
- raw content retention is minimized.

## ITO-504 — Source health and replay

Add operator-visible health, freshness, cache, and replay evidence.

## Phase 5 gate

- live adapters are feature-flagged and fail closed;
- fixture replay passes without network access;
- source outages lower confidence rather than disappearing silently;
- secrets are not exposed;
- source terms and retention policy are documented;
- reference flow still works entirely in fixture mode.

# 10. Phase 6 — Bounded Action Integration

The first real integration must remain draft-only unless a separate authorization ADR approves a specific side effect.

## ITO-601 — Supplier inquiry draft

Preferred first action:

```text
create a reviewable supplier inquiry draft
```

This is safer than placing an order or changing a price.

### Required behavior

- semantic `ActionProposalV1` input;
- human confirmation before any third-party message;
- recipient and content preview;
- expiry and idempotency;
- audit trail;
- no hidden send fallback.

## ITO-602 — Optional test-order draft

Create a non-executing order draft containing quantities, cost ceiling, supplier, assumptions, and measurement plan.

Default mode must not spend money.

## ITO-603 — ActionRouter and Saga integration

Test:

- confirmation;
- duplicate requests;
- timeout;
- cancellation;
- adapter failure;
- compensation or manual recovery;
- terminal-state audit evidence.

## Phase 6 gate

- default installation cannot spend money or contact a third party automatically;
- every consequential action is visible and confirmation-gated;
- duplicate confirmation is idempotent;
- failure and recovery are explainable;
- outcome measurement links back to the exact approved proposal.

# 11. Phase 7 — Read-Only Crypto Research Pack

The purpose is to prove that universal contracts work for a second domain, not to build an autonomous trader.

## ITO-701 — Crypto intent profile

Represent:

- research goals;
- risk tolerance;
- time horizon;
- asset watchlist;
- maximum capital-at-risk context;
- forbidden leverage, custody, signing, and order execution.

Do not add crypto-specific fields to universal contracts unless they are demonstrably universal.

## ITO-702 — Public market evidence

Add read-only price, volume, volatility, liquidity, event-calendar, and project metadata adapters with provenance and replay fixtures.

## ITO-703 — Community signal evidence

Add manipulation-aware social evidence:

- source concentration;
- repeated-origin detection;
- bot/coordination uncertainty;
- attention versus fundamental evidence separation;
- contradictory unlock or liquidity events.

## ITO-704 — Scenario and watchlist modules

Allowed outputs:

- research report;
- watchlist entry;
- scenario conditions;
- risk summary;
- recheck triggers.

Prohibited capabilities:

- exchange order placement;
- wallet signing;
- leverage;
- custody;
- withdrawal;
- automatic position sizing or execution.

## Phase 7 gate

- no trading capability exists in manifests, adapters, routes, or UI;
- all market claims link to evidence and timestamps;
- source concentration and manipulation risks are visible;
- reports distinguish scenarios from predictions;
- the same universal score and outcome contracts work without retail-specific branching.

# 12. Phase 8 — Additional World Interfaces

Each interface is an independent vertical program. None receives blanket authorization from the core manifesto.

Candidate packs:

- local acoustic mapping;
- Wi-Fi CSI presence sensing;
- authorized public-camera observations;
- smart-home control;
- robotics;
- Companion and other sensitive device capabilities.

## Required preparatory work for every pack

1. dedicated ADR;
2. threat model;
3. explicit permissions and consent lifecycle;
4. simulator or recorded fixture environment;
5. data sensitivity and retention design;
6. semantic evidence and action contracts;
7. deterministic policy boundary;
8. manual stop, recovery, or compensation where applicable;
9. focused unit and integration tests;
10. Cold Review before any real adapter is enabled.

## Non-bypass rule

Sensor observations must enter as `EvidenceItemV1`. Device behavior must begin as `ActionProposalV1`. No vertical may bypass the evidence graph, policy engine, ActionRouter, Saga safety, audit, or confirmation boundary.

# 13. Agent Assignment Matrix

| Work type | Primary role | Mandatory second role | Output |
| --- | --- | --- | --- |
| ADR or boundary | Architecture Agent | Reviewer Agent | ADR, paths, non-goals, acceptance tests |
| Contract model | Contract Agent | Test Agent | models, schemas, diagnostics, fixtures |
| Deterministic policy | Implementation Agent | Test Agent | pure functions, property tests, policy version |
| Module package | Implementation Agent | Security Agent | manifest, handler, golden tests, sandbox evidence |
| External source | Implementation Agent | Security Agent + Reviewer | adapter, replay fixtures, threat/terms notes |
| Action integration | Implementation Agent | Security Agent + Test Agent | confirmation, idempotency, recovery evidence |
| Saga Console | Implementation Agent | Reviewer Agent | minimal views, build evidence, no scope creep |
| Release readiness | Reviewer Agent | Human maintainer | merge recommendation, unresolved risks |

The Reviewer Agent must be logically independent from the implementation pass and must not silently repair its own findings.

# 14. PR Template for Every Task

```markdown
## Task

- ID: ITO-XXX
- Phase:
- Manifest section:

## Scope

- ...

## Non-goals

- ...

## Contracts

- Added/changed:
- Compatibility impact:

## Safety and effects

- Capabilities:
- Network:
- Filesystem:
- Secrets:
- Consequential actions:

## Verification

- [ ] focused unit tests
- [ ] focused integration tests, when applicable
- [ ] module validate/test/sandbox, when applicable
- [ ] portfolio gate
- [ ] integration gate, when applicable
- [ ] Saga Console build, when applicable
- [ ] Cold Review

## Evidence

Paste exact commands and summarized results. Do not claim unexecuted checks.

## Remaining limitations

- ...

## Next permitted task

- ITO-...
```

# 15. Task Selection Protocol for Codex

When instructed to continue the plan, Codex must:

1. inspect merged tasks and current branch state;
2. select the earliest unmerged task whose dependencies are satisfied;
3. restate the exact task ID, scope, non-goals, affected paths, and acceptance tests;
4. stop if the task is larger than one reviewable PR;
5. implement only that task;
6. run focused tests first;
7. run required gates;
8. produce the handoff envelope;
9. request or perform a read-only Cold Review;
10. update task status minimally without rewriting unrelated roadmap text.

Codex must not skip ahead because a later task appears easier or more interesting.

# 16. Recommended Execution Order

## First development wave — M0 and M1

```text
ITO-001 Candidate ADR
ITO-002 Package skeleton
ITO-101 Shared primitives
ITO-102 IntentContextV1
ITO-103 EvidenceItemV1
ITO-104 HypothesisV1
ITO-105 OpportunityV1
ITO-106 ActionProposalV1
ITO-107 OutcomeRecordV1
ITO-108 Transition policy
ITO-109 Scoring policy v1
```

## Second development wave — M2

```text
ITO-201 Intent builder
ITO-202 Retail fixture observers
ITO-203 Evidence synthesizer
ITO-204 Hypothesis builder
ITO-205 Evidence critic
ITO-206 Opportunity ranker
ITO-207 Experiment planner
ITO-208 Outcome reviewer
ITO-209 Compatibility suite
```

## Third development wave — M3

```text
ITO-301 Reference flow contract
ITO-302 Simulated action and confirmation
ITO-303 Evidence artifacts
ITO-304 Saga Console Candidate views
ITO-305 End-to-end acceptance test
```

Only after all three waves are green should the team schedule persistence, live sources, bounded real-world actions, or the crypto vertical.

# 17. Go/No-Go Review After the First Milestone

The first milestone receives a **GO** only when all statements below are true:

- the complete flow runs from a clean clone without credentials;
- the result is deterministic under fixed fixtures;
- every recommendation is reconstructable from intent and evidence;
- contradictory evidence is visible;
- scoring is deterministic and inspectable;
- the proposed experiment is bounded and reversible;
- confirmation cannot be bypassed;
- negative outcomes are retained;
- existing active-platform gates remain green;
- no live source, financial action, public action, sensor, or physical-device access was introduced accidentally;
- an independent Cold Review recommends merge.

A **NO-GO** result must identify whether the failure is in:

```text
contract quality
module compatibility
determinism
evidence provenance
policy safety
confirmation behavior
Saga recovery
operator observability
repository gate stability
```

Do not compensate for a NO-GO by broadening scope or adding more agents. Repair the failing layer first.

# 18. Definition of Program Completion

The implementation program is not complete when all task files exist. It is complete when Seed can repeatedly demonstrate that it:

1. understands a confirmed user goal and constraints;
2. observes a bounded domain through authorized or simulated sources;
3. records immutable evidence and provenance;
4. creates falsifiable hypotheses;
5. attacks them with independent criticism;
6. ranks opportunities through deterministic policy;
7. proposes the smallest useful experiment;
8. routes consequential actions through confirmation and Saga safety;
9. measures outcomes, including failures;
10. improves calibration without silently rewriting user preferences;
11. exposes the complete chain to the operator;
12. reuses the same universal contracts in at least two verticals.

Until M3 is complete, the only priority is proving the deterministic retail closed loop. Until M7 is complete, Seed has not yet proven that the platform layer is truly domain-general.