# Seed Intent-to-Outcome Manifest

Status: Candidate platform proposal  
Owner: Seed Platform  
Last updated: 2026-07-17  
Target repository: `CyberSytener/seedServer`

## 1. Product Thesis

Seed must evolve from a system that executes isolated AI workflows into a system that can:

> understand a user's explicit goals and constraints, observe a relevant part of the world, identify evidence-backed opportunities, propose bounded actions, measure outcomes, and improve its private model of what works for that user.

The canonical loop is:

```text
UNDERSTAND -> OBSERVE -> DISCOVER -> VERIFY -> PLAN -> ACT -> MEASURE -> LEARN
```

This document defines the first implementation boundary for that loop. It does not authorize autonomous spending, trading, publishing, surveillance, or physical-device control.

## 2. Why This Belongs Inside Seed

The current platform already provides the necessary execution foundation:

- Contract v1 module manifests and compatibility validation;
- a Module SDK, deterministic tests, sandbox qualification, and signed lifecycle evidence;
- Saga execution with retries, idempotency, confirmations, compensation, tracing, and a DLQ;
- a module registry and visual Saga Console;
- stub providers and deterministic simulation suitable for safe development;
- scoped authentication, policy checks, audit events, and publication gates.

The new work therefore must be an application layer composed from existing contracts and runtime services. It must not create a second workflow engine, a second module registry, or a parallel agent runtime.

## 3. Current Repository Assessment

### Active surfaces to reuse

| Existing surface | Role in Intent-to-Outcome |
| --- | --- |
| `app/contracts/module_contract.py` | stable module boundary and diagnostics |
| `app/services/module_registry.py` | discovery, capability checks, request validation |
| `app/services/flow_contract_validator.py` | typed composition gate |
| `app/module_sdk/` | isolated module implementation surface |
| `app/core/realtime/sagas/` | durable action and workflow execution |
| `app/core/realtime/action_router.py` | confirmation and action routing |
| `app/sim/` | deterministic world and source simulation |
| `app/api/console/` and `saga-console/` | operator inspection and evidence UI |
| `scripts/run_quality_gate.py` | release-blocking validation |

### Candidate surfaces that may be reused carefully

- agent sessions and tool registry;
- provider profiles and real-LLM adapters;
- PostgreSQL and Redis integrations;
- marketplace and domain-specific APIs;
- NeoEats and career flows as implementation references.

Candidate code is not automatically promoted by this proposal.

### Existing market module boundary

`modules/market_scanner.yaml` is a published, job-specific flow block with the task type `job_market_scan`. It must remain job-specific. It must not be renamed, generalized, or overloaded to support retail, crypto, or arbitrary market intelligence.

New generic and vertical modules must receive new stable IDs.

## 4. Scope

### In scope for the first implementation

- explicit user goals, preferences, constraints, and permissions;
- structured evidence with source, timestamp, provenance, and confidence;
- hypotheses that can be supported or contradicted;
- ranked opportunities with transparent scoring;
- bounded experiment or action proposals;
- mandatory confirmation for consequential actions;
- outcome records that compare prediction with result;
- a deterministic retail reference scenario for a small shoe store;
- stub sources and fixtures before live external integrations;
- inspection in Saga Console;
- focused tests and an ADR before promotion to Active.

### Explicitly out of scope

- automatic crypto trading or portfolio management;
- automatic purchases, supplier orders, price changes, advertisements, or public posts;
- hidden inference of sensitive traits or goals;
- optimizing engagement, trading frequency, or spending volume;
- person identification, cross-camera tracking, or covert sensing;
- raw physical-device control by an LLM;
- replacing the existing Module Contract, SDK, Saga runtime, or publication process;
- introducing a generic autonomous “super-agent.”

## 5. Architectural Principle

Only universal concepts belong in the platform layer. Domain knowledge and data acquisition belong in vertical modules.

```text
Saga Console / API
        |
        v
Intent-to-Outcome application services
        |
        v
universal contracts and scoring policies
        |
        v
Contract v1 modules and Saga flows
        |
        v
vertical source/action adapters
```

The platform must know what an `EvidenceItem` or `Opportunity` is. It must not contain hard-coded knowledge of sneaker sizes, token unlocks, road cameras, intimate devices, or Wi-Fi CSI.

## 6. Canonical Domain Contracts

The first slice must introduce versioned Pydantic models and matching portable JSON Schemas. Names below are normative; individual fields may be refined through an ADR before implementation.

### 6.1 `IntentContextV1`

```json
{
  "intent_id": "intent_retail_growth_001",
  "user_id": "user_123",
  "domain": "retail.footwear",
  "goals": [
    {
      "goal_id": "increase_margin",
      "description": "Improve gross margin without increasing stale inventory",
      "priority": 0.9,
      "horizon_days": 90
    }
  ],
  "constraints": {
    "budget_minor": 6000000,
    "currency": "NOK",
    "max_inventory_age_days": 90,
    "requires_human_confirmation": true
  },
  "preferences": {},
  "permissions": {
    "read_market_sources": true,
    "create_action_drafts": true,
    "execute_financial_actions": false
  },
  "confirmed_at": "2026-07-17T10:00:00Z",
  "version": 1
}
```

Rules:

- inferred interests are suggestions, not confirmed goals;
- consequential goals require explicit confirmation;
- every automated capability is independently permissioned;
- the optimization target and forbidden objectives must be represented explicitly.

### 6.2 `EvidenceItemV1`

Required concepts:

- stable evidence ID;
- source type and source reference;
- observation timestamp and ingestion timestamp;
- normalized claim or measurement;
- provenance and transformation chain;
- confidence and quality indicators;
- retention class and sensitivity class;
- optional support/contradiction links.

Evidence is immutable. Corrections create a new item linked to the superseded item.

### 6.3 `HypothesisV1`

A hypothesis contains:

- a falsifiable statement;
- domain and affected goals;
- supporting evidence IDs;
- contradicting evidence IDs;
- assumptions and known confounders;
- expected observations if true;
- observations that would weaken it;
- calibrated confidence;
- lifecycle: `proposed`, `testing`, `supported`, `weakened`, `rejected`, `expired`.

An LLM-generated explanation without linked evidence is not a hypothesis eligible for action planning.

### 6.4 `OpportunityV1`

An opportunity is a hypothesis evaluated against a confirmed user intent.

Minimum fields:

- opportunity ID and domain;
- linked intent and hypothesis IDs;
- expected value range rather than a single fabricated number;
- cost, downside, reversibility, time horizon, and uncertainty;
- score components with policy version;
- evidence freshness;
- proposed smallest useful experiment;
- status: `candidate`, `reviewed`, `approved_for_experiment`, `active`, `completed`, `dismissed`, `expired`.

### 6.5 `ActionProposalV1`

An action proposal is not an executable command. It specifies:

- the goal and opportunity being served;
- semantic action type;
- requested capabilities;
- expected result and measurement plan;
- cost and maximum loss;
- reversibility and compensation plan;
- confirmation class;
- idempotency key;
- expiration time;
- policy decision and explanation.

Only ActionRouter and Saga policy may convert an approved proposal into execution.

### 6.6 `OutcomeRecordV1`

An outcome compares prediction with observation:

- linked action, opportunity, hypothesis, and intent;
- predicted result range;
- observed result and measurement window;
- costs, side effects, and intervention by the user;
- success criteria result;
- attribution confidence;
- lessons and model-policy version;
- whether the outcome may update user preferences.

Outcome records must preserve negative results. The system must not learn only from successful actions.

## 7. Evidence Graph

The first implementation does not require a graph database. A relational or document representation is sufficient if links are explicit and queryable.

```text
IntentContext
   |
   +--> Hypothesis <--- EvidenceItem
             |
             v
        Opportunity
             |
             v
       ActionProposal
             |
             v
          Saga Run
             |
             v
       OutcomeRecord
```

Every user-visible recommendation must be reconstructable from this chain.

## 8. Module Decomposition

The platform must prefer small modules with typed boundaries over one prompt that performs the entire loop.

### Universal modules

Proposed module IDs:

1. `intent_context_builder`
   - converts explicit user input into a draft `IntentContextV1`;
   - marks inferred fields as unconfirmed;
   - performs no external actions.

2. `evidence_synthesizer`
   - normalizes already-collected observations;
   - deduplicates claims and records provenance;
   - does not fetch arbitrary network content itself in the first slice.

3. `hypothesis_builder`
   - creates falsifiable hypotheses from evidence;
   - must produce counter-evidence requirements and confounders.

4. `evidence_critic`
   - attempts to disprove or downgrade each hypothesis;
   - must be structurally independent from the builder prompt and rubric.

5. `opportunity_ranker`
   - applies a deterministic scoring policy to hypotheses and intent constraints;
   - LLM text may explain a score but may not secretly determine it.

6. `experiment_planner`
   - proposes the smallest reversible experiment that can reduce uncertainty;
   - produces `ActionProposalV1` only.

7. `outcome_reviewer`
   - compares predictions with measured outcomes;
   - updates evidence and hypothesis status through an application service.

### Vertical modules

The first vertical pack is `retail.footwear`:

- `retail_catalog_snapshot`;
- `retail_competitor_price_observer`;
- `retail_review_signal_extractor`;
- `retail_supplier_snapshot`;
- `retail_unit_economics`;
- `retail_test_order_draft`.

All first-slice observers use deterministic fixture data. Live source adapters are a later phase and must declare network, secret, rate-limit, and retention policies.

A future crypto pack may provide research, watchlists, scenario analysis, and risk summaries. Its initial capabilities must explicitly exclude order placement, wallet signing, leverage, and custody.

## 9. Reference Flow

The first reference flow should be visible in Saga Console and runnable in stub mode:

```text
confirmed retail intent
  -> fixture market observations
  -> evidence synthesis
  -> hypothesis builder
  -> evidence critic
  -> deterministic opportunity ranking
  -> reversible experiment proposal
  -> simulated human approval
  -> simulated test-order outcome
  -> outcome review
```

Reference story:

> A small shoe store wants to improve margin without holding stale inventory. Seed detects a possible rise in demand for waterproof urban sneakers, finds contradictory quality evidence, recommends ordering samples and a 20-unit test rather than a large purchase, and later compares predicted sell-through with a simulated result.

The demo must show why the opportunity was proposed, which evidence contradicted it, why the action was bounded, and whether the outcome validated the hypothesis.

## 10. Persistence Boundary

Recommended package layout:

```text
app/
  contracts/
    opportunity/
      __init__.py
      models.py
      schemas/
  domain/
    opportunity/
      scoring.py
      policies.py
      transitions.py
  services/
    intent_service.py
    evidence_service.py
    opportunity_service.py
    outcome_service.py
  infrastructure/
    db/
      opportunity_repository.py
modules/
  intent_context_builder/
  evidence_synthesizer/
  hypothesis_builder/
  evidence_critic/
  opportunity_ranker/
  experiment_planner/
  outcome_reviewer/
  retail_*/
tests/
  unit/opportunity/
  integration/opportunity/
  fixtures/opportunity/
docs/
  adr/
```

Rules:

- domain models contain no FastAPI, Redis, database, provider, or UI imports;
- modules import only the stable `app.module_sdk` surface;
- infrastructure implements repository protocols defined above it;
- no module reads `app.state` or imports concrete database adapters;
- API routes remain thin and delegate to application services;
- persistence migrations must be explicit and reversible in development.

## 11. Agent Development Model

Codex development is split into bounded roles. A role is a responsibility and output contract, not necessarily a separate model process.

### 11.1 Architecture Agent

Inputs:

- this manifest;
- active scope, platform roadmap, Module Contract, SDK, test strategy, and relevant ADRs;
- exact issue or phase assignment.

Outputs:

- affected paths;
- contract changes;
- dependency direction;
- risks and non-goals;
- acceptance tests;
- a PR-sized implementation plan.

It must not write production code before identifying the stable boundary.

### 11.2 Contract Agent

Responsibilities:

- define or update Pydantic models and JSON Schemas;
- create machine-readable diagnostics;
- verify backward compatibility;
- create golden valid and invalid fixtures.

It must not add business logic to validation models.

### 11.3 Implementation Agent

Responsibilities:

- implement only the approved slice;
- depend on protocols and stable SDK surfaces;
- preserve deterministic stub behavior;
- avoid opportunistic refactors.

It must not weaken gates or edit lifecycle evidence to make tests pass.

### 11.4 Test Agent

Responsibilities:

- write contract, policy, transition, scoring, module, and integration tests;
- include negative and adversarial cases;
- prove deterministic behavior without paid providers;
- verify that high-impact execution remains blocked without confirmation.

### 11.5 Security and Policy Agent

Responsibilities:

- inspect capabilities, secrets, network/filesystem effects, retention, and sensitive data;
- test prompt-injection and untrusted-source boundaries;
- verify fail-closed behavior;
- confirm that no financial or public side effect can occur through the reference flow.

### 11.6 Reviewer Agent

Responsibilities:

- compare implementation against this manifest and the assigned phase;
- identify scope creep, hidden coupling, missing evidence, and non-determinism;
- reject claims not supported by tests or observable run evidence;
- produce a merge recommendation, never self-approve publication.

### 11.7 Documentation Agent

Responsibilities:

- update architecture, contracts, examples, and operator instructions;
- ensure code paths and commands are real;
- clearly label Active, Candidate, Experimental, and future work.

### Required handoff envelope

Every role must return:

```json
{
  "phase": "phase_1_contracts",
  "scope_completed": [],
  "files_changed": [],
  "contracts_changed": [],
  "tests_added_or_run": [],
  "risks_remaining": [],
  "manifest_deviations": [],
  "next_recommended_slice": ""
}
```

## 12. Codex Execution Protocol

For every implementation task, Codex must:

1. read `SOURCE_OF_TRUTH.md`, `docs/ACTIVE_PLATFORM_SCOPE.md`, this manifest, and `AGENTS.md`;
2. identify the smallest phase or slice that satisfies the request;
3. inspect existing implementations before proposing new abstractions;
4. write or update contracts and tests with the implementation;
5. use stub data until a phase explicitly authorizes live sources;
6. run focused tests, then the required quality gate for the touched surface;
7. report failures honestly and never alter tests merely to hide them;
8. leave financial, physical, public, and privacy-sensitive actions human-gated;
9. avoid unrelated cleanup in the same PR;
10. update documentation when a contract or supported behavior changes.

## 13. Development Roadmap

Each phase is independently reviewable and must keep the existing portfolio demo green.

### Phase 0 — Decision and boundary

Deliverables:

- this manifesto;
- root `AGENTS.md`;
- ADR declaring Intent-to-Outcome a Candidate surface;
- final names and ownership for universal contracts;
- no runtime code.

Exit criteria:

- dependency direction and non-goals are accepted;
- existing active surfaces remain unchanged;
- the first implementation slice is issue-sized.

### Phase 1 — Universal contracts and deterministic policies

Deliverables:

- versioned Pydantic models and JSON Schemas;
- status transition validators;
- deterministic opportunity scoring policy;
- valid, invalid, stale, contradictory, and high-risk fixtures;
- focused unit tests.

Exit criteria:

- schemas reject missing provenance, invalid confidence, and unsupported status transitions;
- scoring is reproducible and inspectable;
- no provider, database, API, or UI dependency exists in domain tests.

### Phase 2 — Stub Contract v1 modules

Deliverables:

- universal module packages and manifests;
- golden tests;
- sandbox qualification in subprocess mode;
- fixture-only retail observer modules;
- compatibility tests for every intended edge.

Exit criteria:

- all modules validate and test through the existing CLI;
- incompatible edges fail before execution;
- no undeclared capability is requested;
- modules do not access the network, arbitrary filesystem, or process APIs.

### Phase 3 — Retail reference flow

Deliverables:

- deterministic Gallery flow;
- Saga Console visualization;
- evidence, hypothesis, opportunity, proposal, and outcome artifacts;
- simulated approval and simulated action adapter;
- end-to-end acceptance test.

Exit criteria:

- the complete story runs without external credentials;
- the operator can inspect support and contradiction evidence;
- a consequential action cannot execute without confirmation;
- the reference demo is repeatable.

### Phase 4 — Persistence and outcome learning

Deliverables:

- repository protocol and SQLite development adapter;
- migrations for intents, evidence, hypotheses, opportunities, proposals, and outcomes;
- append-only evidence and outcome history;
- user-visible correction and deletion controls;
- outcome calibration report.

Exit criteria:

- records are scoped by user/tenant;
- evidence provenance survives restarts;
- failed experiments remain queryable;
- preference updates require policy approval and are reversible.

### Phase 5 — Live retail sources

Deliverables:

- one authorized price/catalog source adapter;
- one authorized review or trend source adapter;
- caching, rate limits, source terms metadata, and fixture replay;
- source health and freshness reporting;
- prompt-injection isolation for untrusted source text.

Exit criteria:

- live adapters can be fully disabled;
- tests replay recorded sanitized fixtures;
- stale or unavailable sources reduce confidence rather than silently disappearing;
- secrets are brokered and never exposed to modules or logs.

### Phase 6 — Bounded action integration

Deliverables:

- draft-only supplier inquiry or test-order proposal;
- ActionRouter confirmation integration;
- Saga compensation where meaningful;
- explicit cost ceiling and expiry;
- audit and outcome measurement.

Exit criteria:

- default mode cannot spend money;
- duplicate confirmations remain idempotent;
- timeout or failure produces an explainable terminal state;
- compensation and manual recovery paths are tested.

### Phase 7 — Read-only crypto research pack

Deliverables:

- public market and community signal adapters;
- provenance-aware social evidence;
- event calendar and risk scenario modules;
- watchlist and research-report actions only.

Exit criteria:

- wallet, exchange-order, leverage, custody, and signing capabilities do not exist;
- source concentration and manipulation risk are surfaced;
- recommendations are scenarios, not guaranteed predictions.

### Phase 8 — Additional world interfaces

Only after the core loop is validated may Seed add vertical packs for:

- public authorized camera observations;
- local acoustic mapping;
- Wi-Fi CSI presence sensing;
- smart-home and robotics actions;
- Companion and other sensitive capabilities.

Each pack requires its own threat model, permissions, retention rules, simulator, and ADR. Sensor and device data must enter the same Evidence and ActionProposal contracts rather than bypassing them.

## 14. Test Plan

### Required unit coverage

- contract validation and serialization stability;
- confidence bounds and freshness rules;
- hypothesis and opportunity lifecycle transitions;
- deterministic score decomposition;
- evidence support/contradiction links;
- action confirmation classes;
- permission and capability denial;
- outcome comparison and preservation of negative results.

### Required integration coverage

- module compatibility across the reference flow;
- fixture observer to outcome reviewer;
- rejection of malformed or injected source content;
- duplicate requests and idempotency;
- expired proposals;
- action denial without confirmation;
- Saga failure and recovery evidence;
- tenant isolation.

### Required validation commands

During Candidate development:

```bash
python -m pytest -q tests/unit/opportunity
python -m pytest -q tests/integration/opportunity
python scripts/run_quality_gate.py portfolio
python scripts/run_portfolio_demo.py --smoke-test --no-open
cd saga-console && npm run build
```

The integration gate becomes mandatory when the Candidate surface receives cross-service behavior.

## 15. Security, Privacy, and Financial Safety

- Minimize data collection and retain normalized evidence instead of raw private content where possible.
- Tag data sensitivity and retention policy at ingestion.
- Never infer sensitive characteristics merely because they could improve ranking.
- Keep user goals editable, inspectable, exportable, and deletable.
- Treat external text, reviews, community posts, and module output as untrusted data.
- Separate data from instructions before any LLM call.
- Require source provenance and freshness for every actionable claim.
- Do not expose secrets to generated modules.
- Apply least-privilege capabilities and fail closed.
- Require confirmation for spending, trading, publishing, contacting third parties, physical actions, or privacy-sensitive observation.
- Store a complete audit trail of proposal, policy decision, confirmation, execution, and outcome.
- Never optimize for transaction count, user compulsion, or emotional vulnerability.

## 16. Definition of Done

A slice is done only when:

- its scope maps to a phase in this document;
- contracts and failure behavior are explicit;
- relevant code follows the declared dependency direction;
- focused positive, negative, and adversarial tests pass;
- existing portfolio gates remain green;
- stub mode remains deterministic;
- capabilities and side effects are declared;
- documentation reflects actual paths and commands;
- no unresolved high-severity security finding remains;
- no consequential action bypasses confirmation;
- the PR records remaining limitations and next work.

“Code exists” is not completion. Evidence that the declared behavior works and fails safely is completion.

## 17. Technical-Debt Prohibitions

The following shortcuts are prohibited:

- adding more product logic to `app/main.py`;
- swallowing broad exceptions during registration or execution;
- importing concrete infrastructure from domain models or SDK modules;
- creating undocumented database tables at arbitrary runtime call sites;
- using free-form LLM prose as an internal contract;
- assigning confidence without recording its basis;
- hiding contradictory evidence;
- changing a published module's meaning without a new module ID or version;
- weakening tests, sandbox policy, lifecycle evidence, or publication gates;
- adding live external sources before deterministic fixtures and replay tests;
- performing irreversible actions in the first implementation;
- committing secrets, raw private datasets, generated runtime artifacts, or local databases.

## 18. First Codex Work Items

Codex should implement these as separate PRs:

1. **ADR and contract package skeleton**
   - add Candidate-surface ADR;
   - create empty package boundaries and contract test skeletons;
   - no API or module behavior.

2. **Universal contract models**
   - implement `IntentContextV1`, `EvidenceItemV1`, `HypothesisV1`, `OpportunityV1`, `ActionProposalV1`, and `OutcomeRecordV1`;
   - add JSON Schemas and invalid fixtures.

3. **Deterministic scoring and transitions**
   - add policy-versioned scoring;
   - add transition rules and focused tests.

4. **First two modules**
   - `intent_context_builder`;
   - fixture-only `retail_catalog_snapshot`;
   - validate, test, and sandbox each package.

5. **Evidence and criticism slice**
   - `evidence_synthesizer`, `hypothesis_builder`, and `evidence_critic`;
   - compatibility and adversarial source tests.

6. **Reference flow**
   - ranking, experiment proposal, simulated approval, outcome review;
   - Gallery entry and deterministic end-to-end test.

Codex must not begin a later item until the prior item's contracts and gates are green or the deviation is explicitly approved.

## 19. Success Criteria for the First Milestone

The first milestone succeeds when a reviewer can run one deterministic command and observe Seed:

1. load a confirmed retail goal;
2. inspect fixture market observations;
3. produce evidence with provenance;
4. form a falsifiable demand hypothesis;
5. display contradictory quality evidence;
6. rank an opportunity using visible score components;
7. propose a small reversible test purchase;
8. require confirmation before simulation;
9. record a simulated sales outcome;
10. explain whether the hypothesis was supported and what should change next.

This milestone proves the reusable Intent-to-Outcome loop. It does not attempt to prove autonomous commerce, market prediction, or general intelligence.
