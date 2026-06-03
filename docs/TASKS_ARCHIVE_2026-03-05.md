# Seed Server — Task Archive (Phases 0–6 + Legacy Reboot History)

> **Archived from** `TASKS.md` on 2026-03-05.
> **Reason:** Phases 0–6 complete. Active tracker reset to Phase 0 (Agent Platform Expansion).
> **Final baseline at archive time:** 903 passed, 22 skipped, 0 failed.

---

# Seed Server — Task Tracker (Roadmap Execution)

**Roadmap source:** `roadmap.md` | **Audit source:** `SERVER_AUDIT_REPORT.md`  
**Last updated:** 2026-02-28  

---

## Phase 0 — Emergency Fixes

| Task | Description | Status | Owner | Updated | Files Touched | Tests | Notes |
|------|-------------|--------|-------|---------|---------------|-------|-------|
| 0.1 | Fix bare `except:` → `except Exception:` with logging | DONE | agent | 2026-02-27 | billing_service.py, path/analytics.py, api/path.py, api/ws/gateway.py, job_board_integration.py | 367 passed, 1 skipped | 10/10 fixed; added logging+logger where missing |
| 0.2 | Add global `Exception` handler (safe 500) | DONE | agent | 2026-02-27 | app/main.py, tests/unit/test_global_exception_handler.py | 369 passed, 1 skipped | Catch-all returns 500 + generic body; no stack trace leak |
| 0.3 | Fix timing-unsafe token check | DONE | agent | 2026-02-27 | app/main.py, tests/unit/test_internal_auth_timing_safe.py | 373 passed, 1 skipped | `hmac.compare_digest()` replaces `!=`; 4 tests |
| 0.4 | Add `USER appuser` to Dockerfile | DONE | agent | 2026-02-27 | Dockerfile | N/A (infra) | `useradd --system appuser`, `chown /data`, `USER appuser` |
| 0.5 | Create `.dockerignore` | DONE | agent | 2026-02-27 | .dockerignore | N/A (infra) | Excludes .env*, .git, tests/, docs/, logs/, node_modules/, IDE files |
| 0.6 | Fix Dockerfile healthcheck | DONE | agent | 2026-02-27 | Dockerfile | N/A (infra) | Now probes `http://localhost:8000/health` via urllib |
| 0.7 | Pin `SQLAlchemy>=2.0,<2.1` | DONE | agent | 2026-02-27 | pyproject.toml | 373 passed, 1 skipped | Was unpinned; now bounded to 2.0.x |

## Phase 1 — Code Hygiene & Observability

| Task | Description | Status | Owner | Updated | Files Touched | Tests | Notes |
|------|-------------|--------|-------|---------|---------------|-------|-------|
| 1.1 | Add `logging.exception()` to all `except Exception: pass` | DONE | agent | 2026-02-27 | 19 files (main.py, auth.py, authz.py, etc.) | 373 passed, 1 skipped | 48 silent `pass` → `logging.debug("Suppressed exception", exc_info=True)` |
| 1.2 | Extract NeoEats chat handler (622 LOC) | DONE | agent | 2026-02-27 | app/api/neoeats_chat.py, app/main.py, tests/unit/test_neoeats_chat_handler.py | 392 passed, 1 skipped | 622 lines extracted, 19 new tests, explicit dependency injection |
| 1.3 | Extract product normalization utils | DONE | agent | 2026-02-27 | app/services/product_normalize.py, app/main.py, tests/unit/test_product_normalize.py | 434 passed, 1 skipped | 13 functions (~304 lines) extracted, 33 new tests |
| 1.4 | Extract store inventory catalog seeding | DONE | agent | 2026-02-27 | app/infrastructure/db/seed_catalog.py, app/main.py, tests/unit/test_seed_catalog.py | 440 passed, 1 skipped | 4 functions + 50-item catalog extracted (182 lines), 6 tests |
| 1.5 | Add `X-Request-ID` middleware | DONE | agent | 2026-02-27 | app/middleware/request_id.py, app/main.py, tests/unit/test_request_id_middleware.py | 396 passed, 1 skipped | Standalone BaseHTTPMiddleware, 4 tests |
| 1.6 | Add auth failure Prometheus metrics | DONE | agent | 2026-02-27 | app/core/metrics.py, app/core/auth.py, tests/unit/test_auth_failure_metrics.py | 401 passed, 1 skipped | AUTH_FAILURES counter with reason label, 7 failure points instrumented, 5 tests |
| 1.7 | Add `[tool.coverage]` to pyproject.toml | DONE | agent | 2026-02-27 | pyproject.toml | 401 passed, 1 skipped | fail_under=50, current coverage 52% |
| 1.8 | Generate lockfile with `pip-compile` | DONE | agent | 2026-02-27 | requirements.lock, Dockerfile | 401 passed, 1 skipped | 112-line lockfile, Dockerfile uses lockfile |

## Phase 2 — CI & Testing Hardening

| Task | Description | Status | Owner | Updated | Files Touched | Tests | Notes |
|------|-------------|--------|-------|---------|---------------|-------|-------|
| 2.1 | Full unit test CI workflow | DONE | agent | 2026-02-27 | .github/workflows/full-tests.yml | 504 passed, 7 skipped | Runs full tests/unit/ with coverage + artifact upload |
| 2.2 | Lint CI workflow (black + flake8 + isort) | DONE | agent | 2026-02-27 | .github/workflows/lint.yml | N/A (CI) | black --check, isort --check, flake8 |
| 2.3 | Add mypy type-checking to lint CI | DONE | agent | 2026-02-27 | .github/workflows/lint.yml | N/A (CI) | mypy --ignore-missing-imports, non-blocking (|| true) |
| 2.4 | Coverage reporting in CI | DONE | agent | 2026-02-27 | .github/workflows/full-tests.yml | N/A (CI) | --cov=app, XML + artifact upload |
| 2.5 | Unit tests for billing_service.py | DONE | agent | 2026-02-27 | tests/unit/test_billing_service.py | 22 passed, 6 skipped | PhotoBillingService + WatermarkService (PIL-dependent tests skipped) |
| 2.6 | Unit tests for catalog_service.py | DONE | agent | 2026-02-27 | tests/unit/test_catalog_service.py | 36 passed | CatalogService with tmp_path fixtures, path traversal guards |
| 2.7 | Unit tests for scheduler.py | DONE | agent | 2026-02-27 | tests/unit/test_scheduler.py | 6 passed | scheduler_loop with mocked RedisQueueHub, race/error paths |
| 2.8 | Rename scripts/test_*.py → debug_*.py | DONE | agent | 2026-02-27 | 9 files in scripts/ | N/A | Prevents pytest autodiscovery confusion |
| 2.9 | Integration test CI with Postgres | DONE | agent | 2026-02-27 | .github/workflows/integration-tests.yml | N/A (CI) | Postgres 16 + Redis 7 service containers |
| 2.10 | Create .pre-commit-config.yaml | DONE | agent | 2026-02-27 | .pre-commit-config.yaml | N/A | black, isort, flake8, trailing-whitespace, check-yaml/json |

## Phase 3 — Async Correctness & Performance

| Task | Description | Status | Owner | Updated | Files Touched | Tests | Notes |
|------|-------------|--------|-------|---------|---------------|-------|-------|
| 3.1 | Async SQLite wrapper (`run_in_executor`) | DONE | agent | 2026-02-28 | app/infrastructure/db/async_sqlite.py, tests/unit/test_async_sqlite.py | 575 passed, 22 skipped | `AsyncSqliteDB` wraps sync `DB` via `run_in_executor`, 7 new tests |
| 3.2 | Replace `time.sleep` → `asyncio.sleep` in retry_logic | DONE | agent | 2026-02-28 | app/core/realtime/retry_logic.py | 575 passed, 22 skipped | `retry_wrapper` now async, added `retry_wrapper_sync` fallback |
| 3.3 | Consolidate rate-limiters (async Redis wins) | DONE | agent | 2026-02-28 | app/api/diagnostics_routes.py, app/api/lessons_routes.py, app/core/rate_limiter.py, app/rate_limiter.py | 575 passed, 22 skipped | Callers migrated to `check_rate_limits()`; sync impl deprecated |
| 3.4 | Remove IndeedScraper + beautifulsoup4 | DONE | agent | 2026-02-28 | app/services/job/search.py, app/main.py, app/core/realtime/sagas/saga_integration.py, pyproject.toml | 575 passed, 22 skipped | Endpoints return 501; data classes retained; bs4 removed |
| 3.5 | Remove statsd dependency | DONE | agent | 2026-02-28 | app/infrastructure/monitoring/monitoring/metrics.py, pyproject.toml | 575 passed, 22 skipped | `init_metrics()` always uses NoOpMetrics; statsd dep removed |
| 3.6 | Remove dead sync saga code path | DONE | agent | 2026-02-28 | app/core/realtime/sagas/orchestrator.py | 575 passed, 22 skipped | `async_mode` param kept for compat; False → raises; always True |

## Phase 4 — Security Hardening

| Task | Description | Status | Owner | Updated | Files Touched | Tests | Notes |
|------|-------------|--------|-------|---------|---------------|-------|-------|
| 4.1 | JWT `audience`/`issuer` validation | DONE | agent | 2026-02-28 | app/core/security/jwt.py, app/settings.py, tests/unit/test_jwt_aud_iss.py | 631 passed, 22 skipped | `sub`/`aud`/`iss` claims in create_token; `audience`/`issuer` in decode; 8 new tests |
| 4.2 | Empty pepper startup warning in production | DONE | agent | 2026-02-28 | app/main.py, tests/unit/test_pepper_warning.py | 631 passed, 22 skipped | Warning logged when `is_production or public_mode` and pepper empty; 4 new tests |
| 4.3 | PII masking filter on root logger | DONE | agent | 2026-02-28 | app/infrastructure/log_utils.py, app/main.py, tests/unit/test_pii_masking.py | 631 passed, 22 skipped | `PIIMaskingFilter` auto-masks emails/keys in all log records; 18 new tests |
| 4.4 | Migrate audit events to DB table | DONE | agent | 2026-02-28 | app/core/authz.py, app/main.py, tests/unit/test_audit_db.py | 631 passed, 22 skipped | `audit_events` SQLite table; DB-first with JSONL fallback; `query_audit_events()`; 15 new tests |
| 4.5 | Auth failure rate-limiting (per-IP lockout) | DONE | agent | 2026-02-28 | app/core/auth.py, tests/conftest.py, tests/unit/test_auth_rate_limit.py | 631 passed, 22 skipped | `AuthFailureRateLimiter` in-memory sliding window; 10 failures/min → 429; 11 new tests |

## Phase 5 — Architecture Refactor (completed prior session)

_main.py 3837→443 lines; LLM unification; DI introduction; shim removal. 656 passed, 22 skipped._

## Phase 6 — Post-Architecture-Map Evidence-Based Tasks

**Source:** `docs/ARCHITECTURE_MAP_POST_PHASE_5.md` §12  
**Branch:** `chore/phase6-tasks`  
**Baseline:** 656 passed, 22 skipped, 1 deselected (95.82 s)

| Task | Pri | Description | Status | Owner | Updated | Files Touched | Tests | Notes |
|------|-----|-------------|--------|-------|---------|---------------|-------|-------|
| T-4 | P1 | Dockerfile `python:3.11-slim` → `python:3.12-slim` (match CI) | DONE | agent | 2026-02-28 | Dockerfile | N/A (infra) | Line 1 changed; matches CI `python-version: "3.12"` |
| T-1 | P1 | Narrow 19 broad `except Exception` in router_registration.py | DONE | agent | 2026-02-28 | app/infrastructure/router_registration.py, tests/unit/test_router_registration_policy.py | 3 passed | 19 broad catches removed; policy docstring added; 3 AST-based tests |
| T-2 | P1 | Register OpenAI + Stub providers in UnifiedLLMService | DONE | agent | 2026-02-28 | app/main.py, tests/unit/test_unified_llm_registration.py | 5 passed | Import + registration for both; Stub always available |
| T-6 | P2 | Verify worker_main.py entrypoint (docker-compose + CI) | DONE | agent | 2026-02-28 | docs/ARCHITECTURE_MAP_POST_PHASE_5.md | N/A (docs) | Photo editing worker; NOT in docker-compose (uses scripts/run_worker.py); doc updated |
| T-5 | P2 | Add middleware order comments (LIFO invariant) | DONE | agent | 2026-02-28 | app/infrastructure/middleware_setup.py, app/main.py | N/A (comments) | Docstring with full LIFO execution order; comments in main.py |
| T-3 | P2 | Add structured metadata methods to UnifiedLLMService | DONE | agent | 2026-02-28 | app/core/llm/protocol.py, app/core/llm/unified.py, tests/unit/test_generation_result.py | 9 passed | GenerationResult dataclass + generate_with_metadata/agenerate_with_metadata; backward compat preserved |

---

# Prior Task History (2026-02-19 Reboot)

_Preserved below for reference. The active tracker is the table above._

---

# Seed Server Refactor Tasks (Reboot — Legacy)

Date: 2026-02-19
Primary audit input: `5.md`
Baseline evidence set: `reports/baseline/2026-02-19/`

## Scope Lock (Non-Negotiable)

1. Canonical source-of-truth is only `seed_server/`.
2. Archive and copy artifacts stay outside active delivery scope.
3. Keep two streams isolated:
   - `chore/archive-cleanup-canonical-root` for archive hygiene only.
   - `refactor/code-fixes-baseline` for code/test/security fixes only.
4. No mixed PRs (archive cleanup and code fixes in the same PR are blocked).

## Current Snapshot (Baseline 2026-02-19)

- Tests: `319 collected`, `6 failed`, `311 passed`, `2 skipped` (`tests_run_q.txt`).
- Route map: `160` HTTP method/path pairs.
- `main.py` inline route decorators: `46` (`main_inline_routes.txt`).
- `app/api` router decorators: `41` (`router_decorators.txt`).
- Duplicate basenames: `38` groups (`duplicate_basenames.json`).
- Duplicate exact-content groups: `6` (`duplicate_content_hash_groups.json`).

Latest verification snapshot (same date, after slices A-Q):

- Tests: `373 collected`, `360 passed`, `13 skipped` (skip set is infra-dependent: Redis/live-server integration checks).
- Route map: `180` HTTP method/path pairs.
- Module registry validation: `[OK] modules/general_assistant.yaml`.

Already in place and should be preserved:

- Route equivalence tests for extracted domains:
  - `tests/unit/test_route_equivalence_auth_admin.py`
  - `tests/unit/test_route_equivalence_jobs.py`
  - `tests/unit/test_route_equivalence_lessons.py`
  - `tests/unit/test_route_equivalence_diagnostics.py`
- LLM router regression tests:
  - `tests/unit/test_llm_router_openai_regression.py`
- CI safety rails:
  - `.github/workflows/security-gates.yml`
  - `.github/workflows/smoke-tests.yml`
  - `.github/workflows/route-registration-sanity.yml`
  - `.github/workflows/module-registry-validation.yml`

## P0 (Blockers, Execute First)

### T0-1: Close baseline test failures (6/6)

Status: Completed (2026-02-19)
Priority: Critical

Failing tests to close:

1. `tests/integration/test_ws_action_flow.py::test_ws_invoke_action_and_confirm_flow`
2. `tests/integration/test_ws_cv_flow.py::test_ws_cv_generation_end_to_end`
3. `tests/integration/test_ws_cv_flow.py::test_ws_cv_generation_with_validation_error`
4. `tests/test_api.py::test_admin_user_creation_requires_configured_admin_key`
5. `tests/unit/realtime/test_llm_pipeline_flow.py::test_llm_pipeline_flow_fails_on_budget_exceeded_time`
6. `tests/unit/test_prompt_baseline_hardening.py::test_diagnostic_generation_falls_back_when_prompt_files_missing`

Primary fix areas:

- Event loop lifecycle handling in WS integration tests.
- JWT test secret length mismatch in WS CV tests.
- Persona error envelope compatibility in API assertion.
- Budget stop-reason precedence in llm pipeline.
- Metrics client call contract (`increment` vs available API).

Definition of done:

- `python -m pytest -q` returns `0` in baseline profile.
- No new regressions in `tests/unit/realtime/*` and `tests/unit/test_security_hardening.py`.
- Execution log:
  - `python -m pytest -q <6 historical nodeids>` -> `5 passed, 1 skipped`.
  - `python -m pytest -q` -> `309 passed, 13 skipped`.

---

### T0-2: Security hardening completion

Status: Completed (2026-02-19)
Priority: Critical

Targets:

- Remove admin env fallback path in auth (`settings.admin_key` must be the single source).
- Keep legacy auth hard-disabled in production profile.
- Keep JWT non-default secret enforcement across auth entry points.

Files:

- `app/core/auth.py`
- `app/settings.py`
- `app/core/security/jwt.py`
- `tests/unit/test_security_hardening.py`
- `tests/test_api.py` (admin provisioning behavior assertions)

Definition of done:

- No authentication path can escalate admin privileges via fallback logic.
- Production profile ignores `SEED_ENABLE_LEGACY_X_USER_ID=1`.
- Empty/default/short JWT secret fails fast and is covered by tests.
- Execution log:
  - Removed admin env fallback in `app/core/auth.py` (`expected_admin = settings.admin_key` only).
  - Added regression: `test_admin_key_env_fallback_is_not_used_when_settings_admin_key_empty`.
  - `python -m pytest -q tests/unit/test_security_hardening.py tests/test_auth_flows.py` -> `19 passed`.

---

### T0-3: LLM budget predictiveness + stop-reason contract

Status: Completed (2026-02-19)
Priority: Critical

Targets from audit `5.md`:

- Add predictive budget guard before expensive steps (`execute`, `repair_loop`).
- Treat `max_wall_time_seconds=0` as disabled (`None`), not immediate timeout.
- Standardize stop reason taxonomy with category/severity in final response.

Files:

- `app/core/realtime/sagas/llm_budget.py`
- `app/core/realtime/sagas/flows/llm_pipeline.py`
- `tests/unit/realtime/test_llm_pipeline_flow.py`
- new focused tests for budget prediction and stop reason schema.

Definition of done:

- Predicted over-budget step is blocked before call execution.
- Budget wall-time zero normalization is deterministic and tested.
- `final_response` includes normalized stop-reason fields.
- Execution log:
  - Added `would_exceed()` and wall-time `<=0 => None` normalization in `app/core/realtime/sagas/llm_budget.py`.
  - Added predictive pre-step budget guard for `execute`/`repair_loop` in `app/core/realtime/sagas/flows/llm_pipeline.py`.
  - Added `stop_category` and `stop_severity` to `final_response`.
  - Updated regression expectations in `tests/unit/realtime/test_llm_pipeline_flow.py`.
  - `python -m pytest -q tests/unit/realtime/test_llm_pipeline_flow.py` -> `12 passed`.

---

### T0-4: Router correctness guardrails (OpenAI path)

Status: Completed (2026-02-19)
Priority: Critical

Targets:

- Re-verify provider call signatures and variable usage in `app/core/llm/router.py`.
- Keep backward compatibility for both Responses API and Chat Completions fallback.

Definition of done:

- Existing regression suite remains green:
  - `tests/unit/test_llm_router_openai_regression.py`
- Add one negative-path test for malformed provider usage payload.
- Execution log:
  - Hardened parser path in `app/core/llm/router.py` for malformed non-dict usage blocks.
  - Added regression: `test_openai_parse_responses_handles_malformed_usage_payload`.
  - `python -m pytest -q tests/unit/test_llm_router_openai_regression.py` -> `5 passed`.

## P1 (Reliability and Delivery Velocity)

### T1-1: Realistic test wiring and simulation maturity

Status: Completed (2026-02-19)
Priority: High

Targets:

- Ensure tests run through production-equivalent `create_app()` wiring.
- Keep deterministic `tests/support/app_factory.py` as the standard helper.
- Keep real-LLM smoke opt-in and secrets-gated (no accidental real provider calls).
- Extend user-request simulation assertions for usage/credits/budget/artifacts parity.

Definition of done:

- No test imports raw global app instance for mutable/shared state scenarios.
- Real-mode tests are skipped unless explicit env flag and keys are present.
- Simulation report contains provider/model/usage/cost metadata for each stage.
- Execution log:
  - Preserved/validated deterministic production-equivalent app wiring:
    - `tests/support/app_factory.py` + `tests/unit/test_app_factory_wiring.py`.
  - Real-LLM smoke path remains explicit-opt-in and secrets-gated:
    - `tests/conftest.py` honors `SEED_TEST_ALLOW_REAL_LLM` and preserves externally supplied provider keys only when enabled.
    - `tests/integration/test_real_llm_smoke.py` and `tests/integration/test_real_simulation_gemini_smoke.py` stay skipped by default unless real-mode env is configured.
  - Extended simulation user-request parity checks:
    - `app/sim/harness.py` now records/asserts per-stage `usage` and `cost`, and probes `llm_pipeline` final `budget_snapshot`, `policy_snapshot`, `pricing_version`, and final artifact refs.
    - `tests/unit/sim/test_simulation_harness.py` updated with parity assertions for:
      - usage/cost metadata
      - budget/policy snapshot presence
      - final/policy artifact references
      - usage-budget and cost-credits parity evidence.
  - `python -m pytest -q tests/unit/sim/test_simulation_harness.py` -> `5 passed`.

---

### T1-4: Credits/pricing contract completion (audit P1 alignment)

Status: Completed (2026-02-19)
Priority: High

Targets:

- Finish provider-agnostic usage/cost/credits normalization across runtime entry points.
- Move pricing rates to versioned config source-of-truth (not hardcoded fallback tables).
- Ensure `execute_llm_request`/router paths emit normalized ledger metadata equivalent to pipeline paths.

Current evidence (already in place):

- Billing contracts exist: `app/services/llm/contracts.py` (`UsageBreakdown`, `CreditLedgerEvent`).
- Existing coverage:
  - `tests/unit/test_llm_billing_contracts.py`
  - `tests/unit/test_diagnostic_cost_accounting.py`
  - `tests/unit/test_lesson_pipeline_cost_accounting.py`
- `pricing_version` is already present in policy snapshots/final response for `llm_pipeline`.

Definition of done:

- Runtime LLM entry points expose normalized usage/cost metadata and ledger event payloads.
- Pricing registry is config-backed and versioned, with test coverage for provider/model fallbacks.
- Simulation and non-saga runtime paths share the same pricing/credits calculation contract.
- Execution log:
  - Added pricing registry:
    - `app/core/llm/pricing.py`
    - `app/core/llm/pricing_catalog.yaml`
  - Extended billing contract payload with pricing provenance:
    - `app/services/llm/contracts.py` now emits `pricing_version` and `matched_pricing_model`.
  - Runtime router now supports metadata mode with normalized usage/cost/ledger output:
    - `app/core/llm/router.py` (`execute_llm_request(..., return_metadata=True)`).
  - Updated diagnostic generation runtime path to consume router ledger metadata:
    - `app/services/diagnostic/engine.py`.
  - Updated real simulation adapter to consume runtime metadata directly:
    - `app/sim/llm_stub.py`.
  - Added/updated regression coverage:
    - `tests/unit/test_llm_pricing_registry.py`
    - `tests/unit/test_llm_billing_contracts.py`
    - `tests/unit/test_llm_router_openai_regression.py`
    - `tests/unit/sim/test_llm_stub_adapter.py`
    - `tests/unit/test_diagnostic_cost_accounting.py`
  - `python -m pytest -q tests/unit/test_llm_billing_contracts.py tests/unit/test_llm_pricing_registry.py tests/unit/test_llm_router_openai_regression.py tests/unit/sim/test_llm_stub_adapter.py tests/unit/test_diagnostic_cost_accounting.py` -> `16 passed`.

---

### T1-5: Eval flywheel (trace grading + trust-or-escalate)

Status: Completed (2026-02-19)
Priority: High

Targets:

- Implement configurable judge cascade in validate step: cheap judge -> escalate on low confidence.
- Persist judge decisions/rationale in artifacts for replayability and audit.
- Add deterministic regression tests for confidence thresholds and escalation behavior.

Current evidence (already in place):

- Candidate generation/ranking exists in `app/core/realtime/sagas/flows/llm_pipeline.py`.
- Policy surface includes quorum/judge strategy metadata in:
  - `app/core/realtime/sagas/llm_policy.py`
  - `app/core/realtime/sagas/llm_orchestration_policy.yaml`

Definition of done:

- Validate step performs cascade grading when policy enables it.
- Final response/artifacts include judge trace and escalation provenance.
- Smoke + unit tests verify quality/cost tradeoff path deterministically.
- Execution log:
  - Added dedicated eval service package:
    - `app/services/evals/judge_cascade.py`
    - `app/services/evals/__init__.py`
  - Moved judge-cascade policy/trace logic from inline pipeline helpers into service layer:
    - `app/core/realtime/sagas/flows/llm_pipeline.py`.
  - Added deterministic quality/cost tradeoff fields in judge trace:
    - `cheap_judge.estimated_cost_units`
    - `escalated_judge.estimated_cost_units`
    - `estimated_total_cost_units`
  - Enabled high-stakes judge ensemble policy config with escalation threshold:
    - `app/core/realtime/sagas/llm_orchestration_policy.yaml`.
  - Added regression coverage:
    - `tests/unit/test_eval_judge_cascade.py`
    - `tests/unit/realtime/test_llm_pipeline_flow.py::test_llm_pipeline_trust_or_escalate_judge_trace_artifact`.
  - `python -m pytest -q tests/unit/test_eval_judge_cascade.py tests/unit/realtime/test_llm_pipeline_flow.py` -> `17 passed`.

---

### T1-2: Main.py blast-radius reduction (next extraction slices)

Status: Completed (Slices D-1, D-2, D-3, D-4 completed on 2026-02-19)
Priority: High

Current state:

- Auth/Admin/Jobs/Lessons/Diagnostics/Career/Actions+Saga/Inventory+Orders+Vision/Learning+Feedback+Monitoring routers are extracted.
- Inventory/Orders/Vision router ownership is extracted.
- `main.py` inline route decorators reduced from `46` to `9`.

Next extraction order:

1. Career domain routes (`/v1/career/*`) `DONE`
2. Action/chat/saga endpoints (`/api/v1/actions/*`, `/api/v1/chat`, `/api/v1/sagas/*`) `DONE (route ownership extracted; logic still closure-backed in main)`
3. Inventory/orders/vision endpoints `DONE (route ownership extracted; logic still closure-backed in main)`
4. Monitoring/feedback/learning profile and recommendations `DONE (route ownership extracted; logic still closure-backed in main)`

Per-slice requirements:

- Zero behavior change.
- Route-equivalence test added or updated per extracted domain.
- One PR per slice.

Definition of done:

- `main.py` inline route decorators reduced from `46` to `<= 20`.
- Route sanity and regression tests remain green.
- Execution log (Slice D-1):
  - Added `app/api/career_routes.py` and moved all `/v1/career/*` endpoints from `app/main.py`.
  - Registered router via `build_career_router(...)` in `app/main.py`.
  - Added parity test: `tests/unit/test_route_equivalence_career.py`.
  - `python -m pytest -q tests/unit/test_route_equivalence_career.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_jobs.py tests/unit/test_route_equivalence_lessons.py tests/unit/test_route_equivalence_diagnostics.py` -> `5 passed`.
  - `python -m pytest -q` -> `323 passed, 2 skipped`.
  - `python scripts/check_route_registration.py` -> `Route sanity passed (160 unique HTTP method/path pairs)`.
- Execution log (Slice D-2):
  - Added `app/api/actions_saga_routes.py`.
  - Removed inline `@app` decorators for:
    - `/api/v1/test/action-echo`
    - `/api/v1/actions/invoke`
    - `/api/v1/chat`
    - `/api/v1/actions/{action_id}/confirm`
    - `/api/v1/actions/{action_id}/cancel`
    - `/api/v1/sagas/{saga_id}`
    - `/api/v1/sagas/{saga_id}/audit`
  - Registered router via `build_actions_saga_router()` and bound closure handlers through `app.state.actions_saga_handlers`.
  - Added parity test: `tests/unit/test_route_equivalence_actions_saga.py`.
  - `python -m pytest -q tests/unit/test_route_equivalence_actions_saga.py tests/unit/test_route_equivalence_career.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_jobs.py tests/unit/test_route_equivalence_lessons.py tests/unit/test_route_equivalence_diagnostics.py` -> `6 passed`.
  - `python -m pytest -q tests/integration/test_ws_action_flow.py tests/integration/test_ws_cv_flow.py` -> `3 passed`.
  - `python -m pytest -q` -> `324 passed, 2 skipped`.
- Execution log (Slice D-3):
  - Added `app/api/inventory_orders_vision_routes.py`.
  - Removed inline `@app` decorators for:
    - `/api/v1/orders/stream` (websocket)
    - `/api/v1/inventory/ledger`
    - `/api/v1/inventory/items` (POST)
    - `/api/v1/inventory/items/{item_id}` (PATCH/DELETE)
    - `/api/v1/inventory/store`
    - `/api/v1/orders/saga/init`
    - `/api/v1/orders`
    - `/api/v1/orders/{order_id}`
    - `/api/v1/vision/analyze`
  - Registered router via `build_inventory_orders_vision_router()` and bound closure handlers through `app.state.inventory_orders_vision_handlers`.
  - Added parity test: `tests/unit/test_route_equivalence_inventory_orders_vision.py`.
  - `python -m pytest -q tests/unit/test_route_equivalence_inventory_orders_vision.py tests/unit/test_route_equivalence_actions_saga.py tests/unit/test_route_equivalence_career.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_jobs.py tests/unit/test_route_equivalence_lessons.py tests/unit/test_route_equivalence_diagnostics.py` -> `7 passed`.
  - `python -m pytest -q tests/integration/test_ws_action_flow.py tests/integration/test_ws_cv_flow.py` -> `3 passed`.
  - `python scripts/check_route_registration.py` -> `Route sanity passed (160 unique HTTP method/path pairs)`.
  - `python -m pytest -q` -> `325 passed, 2 skipped`.
- Execution log (Slice D-4):
  - Added `app/api/learning_feedback_monitoring_routes.py`.
  - Removed inline `@app` decorators for:
    - `/v1/learning/profile`
    - `/v1/learning/profile/upsert`
    - `/v1/learning/profile` (PATCH)
    - `/v1/learning/recommendations`
    - `/v1/learning/plan/generate`
    - `/v1/feedback/bug-reports`
    - `/v1/monitoring/performance`
    - `/v1/monitoring/health`
    - `/v1/monitoring/slo`
    - `/v1/monitoring/slo/{slo_name}/history`
  - Registered router via `build_learning_feedback_monitoring_router()` and bound closure handlers through `app.state.learning_feedback_monitoring_handlers`.
  - Added parity test: `tests/unit/test_route_equivalence_learning_feedback_monitoring.py`.
  - `python -m pytest -q tests/unit/test_route_equivalence_learning_feedback_monitoring.py tests/unit/test_route_equivalence_inventory_orders_vision.py tests/unit/test_route_equivalence_actions_saga.py tests/unit/test_route_equivalence_career.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_jobs.py tests/unit/test_route_equivalence_lessons.py tests/unit/test_route_equivalence_diagnostics.py` -> `8 passed`.
  - `python -m pytest -q tests/integration/test_ws_action_flow.py tests/integration/test_ws_cv_flow.py` -> `3 passed`.
  - `python scripts/check_route_registration.py` -> `Route sanity passed (160 unique HTTP method/path pairs)`.
  - `python -m pytest -q` -> `326 passed, 2 skipped`.

---

### T1-3: Duplicate-module ambiguity cleanup (beyond auth)

Status: Completed (2026-02-19)
Priority: High

Targets:

- Audit high-risk duplicate groups (not package `__init__.py` cases).
- Choose canonical module per functional area.
- Replace stray imports with canonical paths.
- Add temporary compatibility bridges only when migration is phased.

First candidate groups:

- `locks.py`, `circuit_breaker.py` (`app/core/...` vs `app/infrastructure/...`)
- `metrics.py` variants with overlapping responsibility
- `feature_flags.py` variants
- `compat.py` and parser duplicates

Definition of done:

- Duplicate report reduced for high-risk runtime modules.
- Import graph shows one canonical import path per domain service.
- Execution log (part 1):
  - Chosen canonical runtime implementations for realtime engine primitives:
    - `app/infrastructure/realtime/engine/cache.py`
    - `app/infrastructure/realtime/engine/circuit_breaker.py`
    - `app/infrastructure/realtime/engine/db.py`
    - `app/infrastructure/realtime/engine/locks.py`
    - `app/infrastructure/realtime/engine/state.py`
  - Converted duplicate `app/core/realtime/engine/*` files into compatibility bridges that re-export canonical symbols.
  - Added regression coverage: `tests/unit/realtime/test_engine_bridge_imports.py`.
  - `python -m pytest -q tests/unit/realtime/test_engine_bridge_imports.py tests/unit/realtime/test_action_router.py tests/unit/realtime/test_saga_orchestrator.py` -> `47 passed`.
- Execution log (part 2):
  - Converted legacy duplicate `app/diagnostic_core.py` into compatibility bridge to `app/services/diagnostic/core.py`.
  - Canonicalized internal imports:
    - `app/api/admin_routes.py`: `FeatureFlagManager` now imports from `app.core.feature_flags`.
    - `app/api/diagnostics_routes.py`: compat normalization now imports from `app.core.compat`.
    - `app/main.py`: metrics import switched to `app.core.metrics` for internal canonical path.
  - Added bridge regression coverage: `tests/unit/test_duplicate_module_bridges.py`.
  - Verified former exact-duplicate pairs are no longer byte-identical:
    - `app/core/realtime/engine/*` vs `app/infrastructure/realtime/engine/*` (cache/circuit_breaker/db/locks/state)
    - `app/diagnostic_core.py` vs `app/services/diagnostic/core.py`
  - `python -m pytest -q tests/unit/test_duplicate_module_bridges.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_diagnostics.py tests/test_ci_smoke.py` -> `20 passed`.
  - `python -m pytest -q` -> `342 passed, 2 skipped`.

## P2 (Platform Maturity)

### T2-1: Module spec semver and migration contract

Status: Completed (2026-02-19)
Priority: Medium

Targets:

- Extend `scripts/validate_modules.py` contract:
  - `module_version` (semver)
  - `breaking_changes` (bool)
  - `migrations` list
  - `prompt_versions` and `rubric_versions`

Definition of done:

- Validation fails on missing version/migration keys.
- CI (`module-registry-validation`) enforces the new schema.
- Execution log:
  - Extended `scripts/validate_modules.py` contract checks for:
    - `module_version` (semver)
    - `breaking_changes` (boolean)
    - `migrations` (list with object entries)
    - `prompt_versions` (non-empty list of strings)
    - `rubric_versions` (non-empty list of strings)
  - Updated `modules/general_assistant.yaml` with required contract fields.
  - Added regression tests: `tests/unit/test_module_registry_validation_contract.py`.
  - `python -m pytest -q tests/unit/test_module_registry_validation_contract.py tests/unit/test_module_registry.py` -> `9 passed`.
  - `python scripts/validate_modules.py modules` -> `[OK] modules/general_assistant.yaml`.

---

### T2-2: Sandbox publish pipeline hardening for dynamic blocks

Status: Completed (2026-02-19)
Priority: Medium

Targets:

- New module/block publish path must require:
  - dry run
  - simulation harness
  - capability security scan
  - explicit approval gate

Definition of done:

- No direct block registration in production without passing required checks.
- Audit trail is persisted for each publish decision.
- Execution log:
  - Added publish gate service: `app/services/dynamic_publish_gate.py`.
  - Extended dynamic block capability scan with explicit capability/violation output:
    - `app/services/dynamic_block_loader.py` (`scan_capabilities`).
  - Wired publish gate into dynamic block draft flow:
    - `app/api/saga_blueprints.py` now enforces:
      - dry-run status check
      - capability scan
      - optional simulation execution/evidence
      - explicit approval token (required in production profile by default)
    - blocked publish decisions now persist audit entries.
  - Added regression coverage:
    - `tests/unit/test_dynamic_publish_gate.py`.
  - `python -m pytest -q tests/unit/test_dynamic_publish_gate.py` -> `7 passed`.

---

### T2-3: Policy/config versioning layer for orchestration

Status: Completed (2026-02-19)
Priority: Medium

Targets:

- Introduce versioned policy/pricing/prompt/rubric registry surface.
- Ensure `pricing_version` and policy metadata are attached to artifacts/final response.

Definition of done:

- Policy snapshot is reproducible and traceable per run.
- Simulation and production paths consume the same versioned config schema.
- Execution log:
  - Extended orchestration policy surface in:
    - `app/core/realtime/sagas/llm_policy.py`
    - `app/core/realtime/sagas/llm_orchestration_policy.yaml`
  - Added versioned registry fields:
    - `policy_version`
    - `pricing_version`
    - `prompt_registry`
    - `rubric_registry`
  - Added reproducible policy snapshot builder with deterministic fingerprint:
    - `build_policy_snapshot(...)`.
  - Wired policy/pricing snapshot into runtime metadata/final response/artifacts:
    - `app/core/realtime/sagas/flows/llm_pipeline.py`.
    - final response now includes `pricing_version` and `policy_snapshot`.
    - artifacts now include `policy_snapshot_ref` (when artifact store is enabled).
  - Added regression tests:
    - `tests/unit/realtime/test_llm_policy_versioning.py`
    - updated `tests/unit/realtime/test_llm_pipeline_flow.py`.
  - `python -m pytest -q tests/unit/realtime/test_llm_policy_versioning.py tests/unit/realtime/test_llm_pipeline_flow.py` -> `14 passed`.

---

### T2-4: Gemini SDK deprecation cleanup (`google.generativeai` -> `google.genai`)

Status: Completed (2026-02-19)
Priority: Medium

Targets:

- Remove direct runtime dependency on deprecated `google.generativeai`.
- Introduce stable Gemini client abstraction with `google.genai` as primary SDK.
- Keep backward-compat fallback path only when needed.

Definition of done:

- App code no longer imports `google.generativeai` directly.
- Route sanity/import path runs without Gemini deprecation warning.
- Execution log:
  - Added unified Gemini adapter: `app/core/gemini_client.py`.
  - Migrated Gemini call sites to adapter:
    - `app/core/neoeats_blocks.py`
    - `app/core/safety.py`
    - `app/services/flavor_architect.py`
    - `app/services/saga_architect.py`
    - `app/services/saga_reporter.py`
    - `app/services/summary_engine.py`
    - `app/services/trace_analyzer.py`
    - `app/services/receipt_vision_engine.py`
    - `app/services/llm_engine.py`
    - `app/services/job/scorer.py`
  - Updated dependency baseline:
    - `pyproject.toml`: `google-genai>=0.8.0`.
  - `python scripts/check_route_registration.py` -> `Route sanity passed (169 unique HTTP method/path pairs)`.

---

### T2-5: Pydantic `model_*` protected namespace warning cleanup

Status: Completed (2026-02-19)
Priority: Medium

Targets:

- Remove runtime warnings for fields like `model_name` / `model_tier`.
- Apply deterministic model config where those fields are part of API contract.

Definition of done:

- No `model_*` protected namespace warnings in route sanity run.
- Execution log:
  - Added base models with `model_config = {"protected_namespaces": ()}` in:
    - `app/api/saga_blueprints.py`
    - `app/models/vision.py`
  - Added explicit config for realtime action models with `model_name` fields:
    - `app/core/realtime/actions/job_outreach_actions.py`
  - `python scripts/check_route_registration.py` -> `Route sanity passed (169 unique HTTP method/path pairs)`.

## P3 (Enterprise Expansion, After Core Stabilization)

### T3-1: Multi-tenant quotas and governance

Status: Completed (2026-02-19)
Priority: High

Targets:

- Org/project scoping, budget quotas, role/audit model.
- Usage/cost/credits export per tenant.

Definition of done:

- Admin API supports tenant/project/role/quota lifecycle.
- Quota checks and usage recording persist with audit trail.
- Export endpoint returns usage/cost/credits view per tenant/project.
- Execution log:
  - Added tenant governance service and storage layer:
    - `app/services/tenant_governance.py`.
  - Added admin routes:
    - `app/api/tenant_governance_routes.py`.
  - Wired router into app:
    - `app/main.py`.
  - Added integration tests:
    - `tests/unit/test_tenant_governance_api.py`.
  - `python -m pytest -q tests/unit/test_tenant_governance_api.py` -> `2 passed`.

### T3-2: Marketplace model for modules/modes

Status: Completed (2026-02-19)
Priority: High

Targets:

- Public/private module catalog.
- Trust/reputation and sandbox policy constraints.
- Billing and revenue-share flow.

Definition of done:

- Marketplace API supports public catalog listing + private/admin listing access.
- Runtime mode execution enforces marketplace sandbox policy constraints.
- Ratings/reputation and basic revenue-share usage accounting are persisted/exportable.
- Execution log:
  - Added marketplace service/storage layer:
    - `app/services/marketplace.py`.
  - Added marketplace API routes:
    - `app/api/marketplace_routes.py`.
  - Wired marketplace runtime policy/billing context into modes router:
    - `app/api/modes.py`.
  - Wired marketplace router into app factory:
    - `app/main.py`.
  - Added regression coverage:
    - `tests/unit/test_marketplace_service.py`.
    - `tests/unit/test_marketplace_api.py`.
  - `python -m pytest -q tests/unit/test_marketplace_service.py tests/unit/test_marketplace_api.py tests/unit/test_modes_api.py` -> `11 passed`.

### T3-3: Marketplace settlement and payout ledger (cron-ready)

Status: Completed (2026-02-19)
Priority: High

Targets:

- Settlement runner for marketplace usage windows.
- Persistent payout ledger with idempotent windowing.
- Admin API for settlement execution and payout inspection.

Definition of done:

- Settlement writes payout ledger rows with `ready` / `below_minimum` statuses.
- Re-running settlement for the same window does not duplicate payouts.
- Admin API supports run/list/get payout operations.
- Execution log:
  - Extended marketplace storage/service:
    - `app/services/marketplace.py`.
  - Added settlement/payout admin endpoints:
    - `app/api/marketplace_routes.py`.
  - Added cron-friendly settlement runner:
    - `scripts/run_marketplace_settlement.py`.
  - Added service and API coverage:
    - `tests/unit/test_marketplace_service.py`.
    - `tests/unit/test_marketplace_api.py`.
  - `python -m pytest -q tests/unit/test_marketplace_service.py tests/unit/test_marketplace_api.py tests/unit/test_modes_api.py` -> `14 passed`.

## Quality Gates (Must Pass Before Release)

1. Security gates workflow passes.
2. Smoke tests workflow passes.
3. Route registration sanity passes.
4. Module registry validation passes.
5. Full baseline test suite passes with no blocker failures.

## Execution Slices (Next Pass)

1. Slice A: `T0-1` close baseline failures only. `DONE`
2. Slice B: `T0-2` security hardening completion only. `DONE`
3. Slice C: `T0-3` predictive budget + stop-reason normalization. `DONE`
4. Slice D: `T1-2` route extraction slice (career -> actions/saga -> inventory/vision -> monitoring/learning) + parity tests. `DONE`
5. Slice E: `T2-1` module semver validation contract. `DONE`
6. Slice F: `T1-3` duplicate-module cleanup (engine canonicalization, part 1). `DONE`
7. Slice G: `T1-3` duplicate-module cleanup (canonical imports + legacy bridges, part 2). `DONE`
8. Slice H: `T2-2` dynamic publish pipeline hardening. `DONE`
9. Slice I: `T2-3` policy/config versioning layer for orchestration. `DONE`
10. Slice J: `T1-1` realistic wiring + simulation parity maturity. `DONE`
11. Slice K: `T2-4` Gemini SDK deprecation cleanup. `DONE`
12. Slice L: `T2-5` pydantic `model_*` warning cleanup. `DONE`
13. Slice M: `T3-1` multi-tenant quotas/governance rollout. `DONE`
14. Slice N: `T1-4` credits/pricing contract completion across runtime entry points. `DONE`
15. Slice O: `T1-5` eval flywheel (trust-or-escalate judge cascade). `DONE`
16. Slice P: `T3-2` marketplace model (catalog + reputation/sandbox constraints + revenue-share baseline). `DONE`
17. Slice Q: `T3-3` marketplace settlement/payout ledger rollout. `DONE`

## Current Run Log (2026-02-19)

1. Baseline verification:
   - `python -m pytest -q` -> `322 passed, 2 skipped`.
2. Security + router + budget targeted regression:
   - `python -m pytest -q tests/unit/test_security_hardening.py tests/unit/realtime/test_llm_pipeline_flow.py tests/unit/test_llm_router_openai_regression.py` -> `23 passed`.
3. CI smoke subset parity:
   - `python -m pytest -q tests/test_ci_smoke.py tests/test_auth_verify_user_context.py tests/unit/test_security_hardening.py tests/unit/test_llm_router_openai_regression.py` -> `26 passed`.
4. Slice D-1 career extraction parity:
   - `python -m pytest -q tests/unit/test_route_equivalence_career.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_jobs.py tests/unit/test_route_equivalence_lessons.py tests/unit/test_route_equivalence_diagnostics.py` -> `5 passed`.
   - `python -m pytest -q` -> `323 passed, 2 skipped`.
5. Slice D-2 actions+saga route extraction parity:
   - `python -m pytest -q tests/unit/test_route_equivalence_actions_saga.py tests/unit/test_route_equivalence_career.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_jobs.py tests/unit/test_route_equivalence_lessons.py tests/unit/test_route_equivalence_diagnostics.py` -> `6 passed`.
   - `python -m pytest -q tests/integration/test_ws_action_flow.py tests/integration/test_ws_cv_flow.py` -> `3 passed`.
   - `python -m pytest -q` -> `324 passed, 2 skipped`.
6. Slice D-3 inventory/orders/vision route extraction parity:
   - `python -m pytest -q tests/unit/test_route_equivalence_inventory_orders_vision.py tests/unit/test_route_equivalence_actions_saga.py tests/unit/test_route_equivalence_career.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_jobs.py tests/unit/test_route_equivalence_lessons.py tests/unit/test_route_equivalence_diagnostics.py` -> `7 passed`.
   - `python -m pytest -q tests/integration/test_ws_action_flow.py tests/integration/test_ws_cv_flow.py` -> `3 passed`.
   - `python scripts/check_route_registration.py` -> `Route sanity passed (160 unique HTTP method/path pairs)`.
   - `python -m pytest -q` -> `325 passed, 2 skipped`.
7. Slice D-4 learning/feedback/monitoring route extraction parity:
   - `python -m pytest -q tests/unit/test_route_equivalence_learning_feedback_monitoring.py tests/unit/test_route_equivalence_inventory_orders_vision.py tests/unit/test_route_equivalence_actions_saga.py tests/unit/test_route_equivalence_career.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_jobs.py tests/unit/test_route_equivalence_lessons.py tests/unit/test_route_equivalence_diagnostics.py` -> `8 passed`.
   - `python -m pytest -q tests/integration/test_ws_action_flow.py tests/integration/test_ws_cv_flow.py` -> `3 passed`.
   - `python scripts/check_route_registration.py` -> `Route sanity passed (160 unique HTTP method/path pairs)`.
   - `python -m pytest -q` -> `326 passed, 2 skipped`.
8. Slice E module semver contract:
   - `python -m pytest -q tests/unit/test_module_registry_validation_contract.py tests/unit/test_module_registry.py` -> `9 passed`.
   - `python scripts/validate_modules.py modules` -> `[OK] modules/general_assistant.yaml`.
   - `python -m pytest -q` -> `332 passed, 2 skipped`.
9. Slice F duplicate-module cleanup (engine canonicalization part 1):
   - `python -m pytest -q tests/unit/realtime/test_engine_bridge_imports.py tests/unit/realtime/test_action_router.py tests/unit/realtime/test_saga_orchestrator.py` -> `47 passed`.
   - `python -m pytest -q tests/unit/test_module_registry_validation_contract.py tests/unit/test_route_equivalence_learning_feedback_monitoring.py tests/unit/test_route_equivalence_inventory_orders_vision.py` -> `8 passed`.
   - `python -m pytest -q` -> `337 passed, 2 skipped`.
10. Slice G duplicate-module cleanup (part 2):
   - `python -m pytest -q tests/unit/test_duplicate_module_bridges.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_route_equivalence_diagnostics.py tests/test_ci_smoke.py` -> `20 passed`.
   - `python -m pytest -q tests/unit/realtime/test_engine_bridge_imports.py tests/unit/test_module_registry_validation_contract.py` -> `11 passed`.
   - `python scripts/check_route_registration.py` -> `Route sanity passed (160 unique HTTP method/path pairs)`.
   - `python -m pytest -q` -> `342 passed, 2 skipped`.
11. Slice H dynamic publish pipeline hardening:
   - `python -m pytest -q tests/unit/test_dynamic_publish_gate.py` -> `7 passed`.
12. Slice I policy/config versioning:
   - `python -m pytest -q tests/unit/realtime/test_llm_policy_versioning.py tests/unit/realtime/test_llm_pipeline_flow.py` -> `14 passed`.
   - `python -m pytest -q tests/test_ci_smoke.py tests/unit/test_security_hardening.py tests/unit/test_llm_router_openai_regression.py` -> `24 passed`.
   - `python scripts/check_route_registration.py` -> `Route sanity passed (160 unique HTTP method/path pairs)`.
   - `python -m pytest -q` -> `351 passed, 2 skipped`.
13. Slice J realistic wiring + simulation parity maturity:
   - `if (rg -n "from app\\.main import app" tests) { } else { Write-Output "no-global-app-imports" }` -> `no-global-app-imports`.
   - `python -m pytest -q tests/unit/sim/test_simulation_harness.py` -> `5 passed`.
   - `python -m pytest -q tests/unit/realtime/test_llm_policy_versioning.py tests/unit/realtime/test_llm_pipeline_flow.py tests/unit/sim/test_simulation_harness.py` -> `19 passed`.
   - `python scripts/check_route_registration.py` -> `Route sanity passed (160 unique HTTP method/path pairs)`.
   - `python -m pytest -q` -> `351 passed, 2 skipped`.
14. Slice K/L/M deprecation cleanup + tenant governance rollout:
   - `python -m pytest -q tests/unit/test_tenant_governance_api.py tests/unit/test_modes_api.py tests/unit/test_route_equivalence_auth_admin.py tests/unit/test_security_hardening.py tests/unit/sim/test_simulation_harness.py` -> `19 passed`.
   - `python scripts/check_route_registration.py` -> `Route sanity passed (169 unique HTTP method/path pairs)`.
   - `python -m pytest -q` -> `353 passed, 2 skipped`.
15. Audit re-check verification run:
   - `python -m pytest -q` -> `353 passed, 2 skipped` (`355 collected`).
   - `python scripts/check_route_registration.py` -> `Route sanity passed (169 unique HTTP method/path pairs)`.
   - `python scripts/validate_modules.py modules` -> `[OK] modules/general_assistant.yaml`.
   - `python -m pytest -q tests/unit/test_tenant_governance_api.py tests/unit/sim/test_simulation_harness.py tests/unit/realtime/test_llm_policy_versioning.py tests/unit/realtime/test_llm_pipeline_flow.py` -> `21 passed`.
16. Slice N/O runtime pricing + eval-cascade progress:
   - `python -m pytest -q tests/unit/test_llm_billing_contracts.py tests/unit/test_llm_pricing_registry.py tests/unit/test_llm_router_openai_regression.py tests/unit/sim/test_llm_stub_adapter.py tests/unit/test_diagnostic_cost_accounting.py tests/unit/realtime/test_llm_pipeline_flow.py` -> `29 passed`.
   - `python -m pytest -q` -> `358 passed, 2 skipped` (`360 collected`).
   - `python scripts/check_route_registration.py` -> `Route sanity passed (169 unique HTTP method/path pairs)`.
   - `python scripts/validate_modules.py modules` -> `[OK] modules/general_assistant.yaml`.
17. Slice O completion (eval service extraction + deterministic tradeoff checks):
   - `python -m pytest -q tests/unit/test_eval_judge_cascade.py tests/unit/realtime/test_llm_pipeline_flow.py tests/unit/test_llm_router_openai_regression.py tests/unit/test_llm_pricing_registry.py tests/unit/test_llm_billing_contracts.py tests/unit/sim/test_llm_stub_adapter.py` -> `32 passed`.
   - `python -m pytest -q` -> `362 passed, 2 skipped` (`364 collected`).
   - `python scripts/check_route_registration.py` -> `Route sanity passed (169 unique HTTP method/path pairs)`.
   - `python scripts/validate_modules.py modules` -> `[OK] modules/general_assistant.yaml`.
18. Slice P completion (marketplace model baseline rollout):
   - `python -m pytest -q tests/unit/test_marketplace_service.py tests/unit/test_marketplace_api.py tests/unit/test_modes_api.py` -> `11 passed`.
   - `python -m pytest -q tests/test_ci_smoke.py tests/test_auth_verify_user_context.py tests/unit/test_security_hardening.py tests/unit/test_llm_router_openai_regression.py` -> `27 passed`.
   - `python scripts/check_route_registration.py` -> `Route sanity passed (177 unique HTTP method/path pairs)`.
   - `python scripts/validate_modules.py modules` -> `[OK] modules/general_assistant.yaml`.
   - `python -m pytest -q` -> `368 passed, 2 skipped` (`370 collected`).
19. Slice Q completion (marketplace settlement + payout ledger):
   - `python -m pytest -q tests/unit/test_marketplace_service.py tests/unit/test_marketplace_api.py tests/unit/test_modes_api.py` -> `14 passed`.
   - `python -m pytest -q tests/test_ci_smoke.py tests/test_auth_verify_user_context.py tests/unit/test_security_hardening.py tests/unit/test_llm_router_openai_regression.py` -> `27 passed`.
   - `python scripts/check_route_registration.py` -> `Route sanity passed (180 unique HTTP method/path pairs)`.
   - `python scripts/validate_modules.py modules` -> `[OK] modules/general_assistant.yaml`.
   - `python -m pytest -q` -> `360 passed, 13 skipped` (`373 collected`).
   - `python -m pytest -q tests/test_api.py tests/unit/test_bug_report.py -rs` -> integration skips explained by unavailable Redis/live local server in current environment.
   - `python scripts/run_marketplace_settlement.py --db-path .seed_artifacts/marketplace_settlement_smoke.db --run-id settlement_smoke_1` -> smoke run succeeded (`created_count=0` on empty catalog).

## Instructions For Codex (Next Pass)

1. Do not mix archive cleanup and code fixes in one commit/PR.
2. For each slice: implement -> run targeted tests -> run smoke subset -> update `reports/baseline/<date>/`.
3. Keep changes behavior-preserving unless the task explicitly changes behavior.
4. Add or update regression tests with every functional fix.
5. Preserve production-safe defaults:
   - legacy auth OFF in production
   - dev seeding OFF by default
   - dev CORS only by explicit opt-in
6. After each slice, update this file with status and evidence links.