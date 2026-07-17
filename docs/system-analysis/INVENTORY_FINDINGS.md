# Quantitative Repository Findings And Target Route

Status: Cold Review input  
Repository: `CyberSytener/seedServer`  
Analyzed PR head: `d69292c2a5e04ea687a7983eddef49bffea29652`  
Canonical product baseline: `main@eee84040fd8388e842d45b1e099dcd898574fd01`  
Workflow: `system-analysis` run `29579298916`  
Artifact: `seed-system-analysis`, id `8406323641`, digest `sha256:b7c84c181693c20ad4199355c2febe39b2d1a4935903c03ac95e9fa6a9c58c18`

## 1. Interpretation Boundary

This report combines deterministic static inventory with targeted source inspection.

- **Observed** metrics come from the uploaded `inventory.json` artifact.
- **Verified** workflow claims refer to the green GitHub Actions runs on the named PR head.
- **Declared** product status comes from maintained scope, test, roadmap, manifest, plan, and ADR documents.
- **Inferred** architecture findings are reasoned conclusions and still require focused runtime proof before they become Verified.

Important limitations:

1. the 287 route count is a repository-wide route **signal** count and includes test and documentation examples, not only deployed endpoints;
2. Pydantic, Protocol, broad-catch, placeholder, and TODO counts include Active, Candidate, Experimental, historical, test, and script files;
3. configured surface counts overlap — for example, an Active focused test may also live under the broad Experimental `tests/unit/**` inventory;
4. import edges show static dependency direction, not runtime frequency or ownership intent;
5. broad exception handlers are review signals, not automatically bugs;
6. zero configured boundary violations means the current profile rules passed, not that every desirable architecture rule already exists.

## 2. Repository Scale

| Metric | Observed value |
| --- | ---: |
| Tracked files included by the analysis profile | 1,137 |
| Python files | 723 |
| Python source lines | 174,946 |
| Test files | 205 |
| Markdown documentation files | 221 |
| Route signals | 287 |
| Pydantic model classes | 390 |
| `Protocol` interfaces | 21 |
| GitHub Actions workflows | 13 |
| Configured dependency-boundary violations | 0 |
| Python parse errors | 1 |
| Broad `Exception`/`BaseException`/bare handlers | 895 |
| `pass` statements | 127 |
| TODO/FIXME/HACK markers | 22 |

The correct mental model is therefore a large mixed-maturity platform repository, not a small FastAPI application. The analysis and delivery process must remain surface-aware and gate-aware; repository-wide refactors would be high-risk and poorly aligned with the target.

## 3. Declared Surface Footprint

| Surface | Declared status | Files | Python files | Matched test files |
| --- | --- | ---: | ---: | ---: |
| Portfolio launcher | Active | 2 | 2 | 1 |
| Saga Console | Active | 38 | 0 | 0 |
| Console control plane | Active | 7 | 7 | 1 |
| Module registry and SDK | Active | 50 | 38 | 5 |
| Saga runtime | Active | 62 | 61 | 27 |
| Stub simulation | Active | 9 | 9 | 3 |
| Intent-to-Outcome | Candidate | 14 | 9 | 7 |
| NeoEats | Candidate | 46 | 29 | 12 |
| Production infrastructure | Candidate | 83 | 77 | 0 under the configured surface paths |
| Broad historical unit suite | Experimental | 149 | 149 | 149 |

### Interpretation

The supported platform is substantially smaller than the whole repository, which validates the existing Active/Candidate/Experimental policy. At the same time, the Active Saga and Module SDK surfaces are already non-trivial systems. New Intent-to-Outcome work should integrate through their stable boundaries rather than duplicate execution, publication, sandbox, confirmation, or observability mechanisms.

## 4. Complexity Concentration

The top source hotspots are:

| File | Lines | Functions | Classes | Broad catches |
| --- | ---: | ---: | ---: | ---: |
| `app/core/neoeats_blocks.py` | 2,934 | 74 | 25 | 18 |
| `app/core/realtime/sagas/orchestrator.py` | 2,287 | 47 | 1 | 32 |
| `app/api/neoeats_profile_routes.py` | 1,825 | 61 | 0 | 27 |
| `app/core/realtime/sagas/flows/legacy.py` | 1,627 | 18 | 7 | 27 |
| `modules/bot/planner.py` | 1,577 | 24 | 2 | 0 |
| `app/api/console/utils.py` | 1,521 | 48 | 6 | 11 |
| `app/core/realtime/sagas/saga_health.py` | 1,357 | 23 | 19 | 23 |
| `app/services/neoeats_recipe_card.py` | 1,345 | 37 | 0 | 8 |
| `app/api/inventory_orders_vision_routes.py` | 1,246 | 36 | 0 | 16 |
| `app/api/saga_blueprints.py` | 1,223 | 35 | 23 | 10 |
| `app/infrastructure/llm/client.py` | 1,186 | 13 | 4 | 3 |
| `app/models/api.py` | 1,158 | 1 | 106 | 0 |
| `app/core/agent/session.py` | 1,143 | 24 | 2 | 9 |
| `app/core/realtime/sagas/flows/llm_pipeline.py` | 1,126 | 38 | 1 | 5 |

### Finding SYS-P2-001 — Complexity is clustered, not uniformly distributed

**Evidence class:** Observed  
**Severity:** P2

The largest maintenance and regression risk is concentrated in NeoEats, Saga orchestration, legacy flows, Console helpers, health/recovery, and broad API-model collections. This does not justify a repository-wide cleanup. Extraction should be target-driven:

- touch the Saga orchestrator only through focused adapter ports required by M3;
- keep retail logic in Contract v1 vertical modules rather than expanding `neoeats_blocks.py`;
- avoid adding new universal models to `app/models/api.py`;
- avoid adding new router families to the optional-router registry until a responsibility is promoted and intentionally composed.

## 5. Dependency Direction

Notable aggregated import edges inside production packages:

| Source | Target | Static imports |
| --- | --- | ---: |
| `app.api` | `app.core` | 71 |
| `app.api` | `app.services` | 61 |
| `app.api` | `app.infrastructure` | 38 |
| `app.services` | `app.core` | 31 |
| `app.services` | `app.infrastructure` | 28 |
| `app.infrastructure` | `app.core` | 31 |
| `app.infrastructure` | `app.api` | 21 |
| `app.core` | `app.services` | 16 |
| `app.core` | `app.infrastructure` | 10 |
| `app.main` | `app.infrastructure` | 14 |
| `app.main` | `app.api` | 12 |

### Finding SYS-P2-002 — The repository is not a clean one-way layered architecture

**Evidence class:** Observed and Inferred  
**Severity:** P2 generally; P1 when a target crosses these boundaries

Bidirectional edges exist between core, services, infrastructure, and API. A concrete example is `app/infrastructure/router_registration.py`, which imports and composes 21 API/router families and also constructs agent runtime dependencies. This is operationally understandable as a composition helper but means directory names alone cannot establish dependency ownership.

Target route rule:

- introduce explicit ports only at the boundaries needed by Intent-to-Outcome;
- enforce those ports with focused AST/import tests;
- do not attempt a global package-layer rewrite;
- keep new Candidate contracts independent of FastAPI, concrete persistence, providers, `app.main`, and concrete LLM services.

## 6. Composition And Configuration

Observed signals:

- 146 composition calls such as `include_router`, `mount`, middleware registration, and registry calls;
- `app/core/blocks.py` contains 40 composition/registration signals;
- `app/infrastructure/router_registration.py` contains 21 router composition calls;
- `app/main.py` contains 13 composition calls and still selects SQLite, Redis, providers, NeoEats engines, realtime wiring, startup schema initialization, and inline internal routes;
- 165 distinct environment-variable names are referenced 316 times in Python source.

Frequently referenced names include `GEMINI_API_KEY`, `SEED_TEST_AUTH_MODE`, `DATABASE_URL`, `SEED_GEMINI_MODEL_FAST`, `SEED_ADMIN_KEY`, `SEED_DB_PATH`, and `SEED_SAGA_DB_URL`.

### Finding SYS-P2-003 — Composition ownership and configuration surface are broad

**Evidence class:** Observed  
**Severity:** P2

The project already extracted substantial router registration and infrastructure wiring out of `main.py`, so the earlier “5,000-line god file” concern is no longer accurate. However, startup remains the point where several different maturity levels and storage/runtime modes are selected.

Route rule:

- new Candidate work must not be registered in `create_app()` during Phase 1;
- M3 composition should enter through one explicit feature registration boundary with deterministic stub defaults;
- later persistence/live-source work needs a typed settings and secret matrix rather than additional scattered `os.getenv` calls;
- each production adapter must declare startup, health, timeout, shutdown, and degraded-mode behavior.

## 7. Quality And Verification

The quality runner exposes four explicit modes:

```text
portfolio
intent-to-outcome
integration
experimental
```

The Candidate gate currently covers:

- the quality-gate runner contract;
- `tests/unit/opportunity`;
- flow graph and contract validation;
- canonical executor import boundary;
- fail-closed cycle rejection;
- `tests/integration/opportunity`.

The portfolio gate contains 17 explicit entries covering the demo, Console, auth providers and limits, Module Contract/registry/SDK/CLI, flow safety, modes, security, LLM routing regression, and simulation.

### Finding SYS-STRENGTH-001 — Release promises are explicit and separable

**Evidence class:** Declared and Verified

This is one of the strongest parts of the repository. Candidate work can gain real blocking evidence without silently becoming part of the Active product promise. Preserve this distinction through M1 and M2; add runtime integration and reviewer-demo evidence only when M3 starts changing Active Saga/Console behavior.

## 8. Static Hygiene Findings

### SYS-P2-004 — Corrupted backup file is tracked inside a production namespace

**Evidence class:** Observed  
**Severity:** P2 hygiene, not a runtime blocker

`app/services/prompt_testing_backup.py` fails Python parsing at line 139 because a large code block is stored with literal `\n` characters. The active application does not appear to import this backup, but its location causes static tooling to treat it as production source.

Recommended independent slice:

```text
HYGIENE-001
- verify no imports or operational references exist;
- remove the file or move its historical content outside production namespaces;
- add a repository parse/compile check for included Python source;
- do not combine this cleanup with Intent-to-Outcome contracts.
```

### SYS-P2-005 — Broad exception handling requires target-specific review

**Evidence class:** Observed  
**Severity:** P2 signal

The inventory found 895 broad handlers across the repository. This count includes tests, historical and optional surfaces, so it is not a defect count. Nevertheless, files on the M3 path must be reviewed for whether broad catches:

- preserve cancellation;
- distinguish transient from permanent failure;
- emit audit/trace evidence;
- avoid converting partial external effects into apparent success;
- retain deterministic failure codes.

## 9. Current P0 Gaps For The M3 Target

### SYS-P0-001 — No implemented SDK-module execution port into the active flow runtime

**Evidence class:** Observed  
**Severity:** P0 for M3; not a blocker for ITO-102

Current code search finds `ModuleExecutionPort` only in the architecture audit/plan. The Active Module SDK can validate, sandbox, qualify, collect evidence for, and publish Contract v1 packages, while `FlowExecutorSaga` executes registered flow blocks. A supported adapter joining these systems is not implemented.

Required remediation:

1. define `ModuleExecutionRequest`, result, typed failure, timeout, cancellation, evidence, and capability interfaces;
2. adapt existing built-in block execution without behavior drift;
3. add a sandboxed SDK module adapter that only consumes qualified/published evidence;
4. make validation and runtime select the same adapter semantics;
5. protect the boundary with deterministic fixtures, import tests, timeout/cancellation tests, and artifact/audit assertions.

### SYS-P0-002 — No implemented canonical ActionProposal policy gateway

**Evidence class:** Observed  
**Severity:** P0 before any real consequential action

Current code search finds `ActionProposal` primarily in maintained Intent-to-Outcome documents and the primitive lifecycle enum/tests. It does not find a completed typed proposal model and gateway that binds a semantic proposal to `ActionRouter` execution.

Required remediation:

```text
vertical module or planner
  -> ActionProposalV1
  -> ProposalPolicyGateway
  -> typed PolicyDecision
  -> confirmation and expiry
  -> idempotent simulated executor
  -> expected-vs-observed measurement
  -> OutcomeV1 and audit evidence
```

The gateway must bind tenant/user, capability, policy version, confirmation class, cost/intensity ceiling, expiry, idempotency, expected result, measurement plan, reversibility, compensation, and audit evidence. Until this exists and a later ADR authorizes a bounded effect, all ITO actions remain simulation-only.

## 10. P1 Gaps Before Persistence, Live Sources, Or Real Effects

### SYS-P1-001 — Durable confirmation and restart-safe exactly-once semantics

Existing Saga mechanisms are valuable, but the target needs proposal-bound proof across restart boundaries:

- confirmation recorded before dispatch;
- no duplicate effect after retry/restart;
- provider acknowledgement and idempotency linked to the same proposal;
- expiry and cancellation respected;
- partial-effect recovery visible to the operator.

### SYS-P1-002 — Universal repository and migration boundary

Before M4, define protocols and explicit Alembic migrations for immutable evidence, hypotheses, opportunities, proposals, outcomes, corrections, negative evidence, tenant/user identity, sensitivity, retention, freshness, and deletion behavior.

Phase 1 must not create tables.

### SYS-P1-003 — Evidence sensitivity and retention policy

Fixture evidence cannot simply become private or live evidence later. Storage and inspection must enforce tenant scope, sensitivity, retention, expiry, correction/supersession, auditability, and redaction.

## 11. Readiness Verdict

| Target slice | Verdict | Reason |
| --- | --- | --- |
| Analysis foundation | PROMOTION-READY after PR Cold Review | Analyzer, tests, fail-closed CI, diagnostic artifact, protocol, target and route documentation are present and green. |
| `ITO-102 IntentContextV1` | IMPLEMENTATION-READY | Pure immutable Candidate contract; merged prerequisites exist; no runtime, storage, API, provider or UI change required. |
| Remaining M1 contracts and deterministic policies | IMPLEMENTATION-READY slice by slice | Must preserve domain neutrality and schema/gate discipline. |
| M2 fixture-only vertical modules | NO-GO until M1 exit gate | Requires complete universal language and deterministic policies. |
| M3 deterministic closed loop | REMEDIATION-READY | Requires the SDK execution port and proposal-policy/simulation boundary. |
| M4 universal persistence | NO-GO | Repository, migration, tenancy, retention and correction semantics incomplete. |
| M5 live observation | NO-GO | Authorization, sanitized replay, freshness, outage and injection isolation absent. |
| M6 real consequential action | NO-GO | No approved bounded-action ADR or complete proposal/confirmation/recovery proof. |
| Sensors and devices | NO-GO | Separate simulator, threat model, permissions, semantic-action layer and ADR required. |
| Candidate-to-Active promotion | NO-GO | Full product responsibility, owner, operational policy, demo evidence and release-blocking tests are incomplete. |

## 12. Recommended Route

```text
ANALYSIS-001  merge repeatable analysis infrastructure
      |
      +--> HYGIENE-001 remove/relocate corrupted tracked backup
      |
      v
ITO-102       IntentContextV1 fixtures, schema, tests, Candidate gate, Cold Review
      |
      v
ITO-103..108  Evidence, Hypothesis, Opportunity, ActionProposal, Outcome,
             lifecycle transitions and deterministic policies
      |
      +------------------------------+
      |                              |
      v                              v
RUNTIME-PORT-001                     POLICY-GATE-001
built-in + SDK execution port        proposal decision + simulation adapter
      |                              |
      +---------------+--------------+
                      v
M2 fixture-only retail-footwear Contract v1 modules
                      |
                      v
M3 deterministic reference flow in stub mode
                      |
                      v
Saga Console inspection of evidence, hypothesis, opportunity,
proposal, policy decision, simulated action, measurement and outcome
```

### Route constraints

- `agent/ito-102-intent-context-v1` remains a separate incomplete branch and must not be merged into the analysis PR;
- rebase or recreate ITO-102 from canonical `main` after ANALYSIS-001 merge to avoid unrelated branch history;
- no API, DB, provider, UI, live source or real-effect work belongs in ITO-102;
- runtime remediation uses separate branches and focused gates;
- retail business logic belongs in fixture-only Contract v1 modules, not universal core contracts or additional NeoEats monolith branches;
- the first M3 flow must use stub providers and simulated actions only;
- M4+ stages require separate GO decisions.

## 13. Cold Review Result

```json
{
  "review_result": "approve",
  "scope_compliance": [
    "analysis PR changes no application runtime, API, persistence, provider, UI, or ITO contract behavior",
    "generated artifacts remain ignored and workflow-retained",
    "secret and local-data exclusions are explicit and tested",
    "analysis claims distinguish declared, observed, verified, and inferred evidence"
  ],
  "contract_risks": [
    "surface counts overlap by design and must not be summed as disjoint ownership",
    "static route and model counts include non-runtime files"
  ],
  "security_risks": [
    "none blocking in the analysis infrastructure; scanner records environment names only"
  ],
  "test_gaps": [
    "future analyzer versions may add explicit runtime-only route and package-edge views"
  ],
  "hidden_coupling": [
    "infrastructure-to-API composition",
    "core/services/infrastructure bidirectional imports",
    "startup composition across mixed maturity surfaces"
  ],
  "unsupported_claims": [],
  "required_changes": []
}
```

## 14. Handoff

```json
{
  "audited_ref": "main@eee84040fd8388e842d45b1e099dcd898574fd01",
  "analysis_head": "d69292c2a5e04ea687a7983eddef49bffea29652",
  "target_id": "SEED-ITO-M3",
  "readiness": "REMEDIATION-READY",
  "implementation_ready_checkpoint": "ITO-102",
  "p0_findings": [
    "missing SDK-module flow execution port",
    "missing canonical ActionProposal policy gateway"
  ],
  "p1_findings": [
    "durable proposal confirmation and restart-safe exactly-once proof",
    "universal repository and migration boundary",
    "sensitivity and retention-aware evidence policy"
  ],
  "consequential_effects_authorized": false,
  "next_recommended_slice": "merge ANALYSIS-001, then complete ITO-102 as a clean pure-contract PR"
}
```
