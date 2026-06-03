# Test Coverage Cleanup - 2026-05-20

This note marks the status of deleted tracked tests after the cleanup/import audit. It is a coverage map, not a request to restore old files blindly.

## Snapshot

- Deleted tracked tests reviewed: `20`
- Deleted legacy script tests reviewed: `4`
- Current priority: keep NeoEats, auth, CI/security, realtime contracts and public smoke green before restoring lower-priority legacy coverage.
- Current risk: some old learning/path/diagnostic streaming tests were removed before their replacements were fully normalized under `tests/unit` or `tests/integration`.

## Deleted Test Groups

| Deleted group | Files | Current interpretation |
| --- | ---: | --- |
| Legacy async/diagnostic/placement tests | `7` | Do not restore as-is. Diagnostic code moved under `app/services/diagnostic/*`; add focused tests there when touching diagnostic generation/session behavior. |
| Legacy learning path/adaptive tests | `5` | Product-lower-priority for NeoEats beta. Keep current path APIs stable, but require new tests before path feature work. |
| Legacy streaming/integration broad smoke | `3` | Rebuild as smaller route/service tests if streaming endpoints become active product surface again. |
| Legacy batch/optimizer tests | `2` | Covered only partially by current optimizer/import checks. Restore targeted tests before optimizer changes. |
| Legacy generic integration/load/mode/translate tests | `3` | Historical broad checks. Keep archived unless a current route loses equivalent coverage. |

Deleted tracked test files:

- `tests/integration/test_async_endpoints.py`
- `tests/integration/test_learning_path_simple.py`
- `tests/integration/test_path_analytics.py`
- `tests/integration/test_path_integration.py`
- `tests/integration/test_path_models.py`
- `tests/integration/test_placement_async_final.py`
- `tests/integration/test_placement_proof.py`
- `tests/integration/test_placement_simple.py`
- `tests/integration/test_streaming_comprehensive.py`
- `tests/test_adaptive_learning.py`
- `tests/test_diagnostic_session.py`
- `tests/test_diagnostic_simple.py`
- `tests/test_integration.py`
- `tests/test_load_blueprint.py`
- `tests/test_mode_prompts.py`
- `tests/test_translate_validation.py`
- `tests/unit/test_batch_metrics_eval.py`
- `tests/unit/test_batch_runner.py`
- `tests/unit/test_diagnostic_async.py`
- `tests/unit/test_diagnostic_async_auto.py`

Deleted legacy script tests:

- `scripts/test_multi_phase.py`
- `scripts/test_multi_phase_one_iter.py`
- `scripts/test_multi_phase_stats.py`
- `scripts/test_phase3_debug.py`

## Active Replacement Coverage

Keep these checks as the current release gates:

```powershell
python -m pytest -q tests\test_ci_smoke.py tests\test_auth_verify_user_context.py tests\unit\test_security_hardening.py tests\unit\test_llm_router_openai_regression.py
python -m pytest -q tests\test_ci_smoke.py tests\unit\test_auth_open_registration.py tests\unit\test_neoeats_rag_memory.py tests\unit\test_receipt_confirm_routes.py
python -m pytest -q tests\unit\realtime\test_engine_bridge_imports.py tests\unit\realtime\test_action_router.py tests\unit\realtime\test_contracts.py tests\test_ci_smoke.py
.\scripts\smoke_public_neoeats.ps1
```

Latest verified backend gate in this pass:

- `41 passed` for CI/auth/security/LLM/NeoEats receipt-memory/diagnostic serialization/lesson pipeline cost accounting.
- `tests/unit/test_lesson_pipeline_cost_accounting.py` now passes after hardening `app.core.validators.validators.repair`.
- Public NeoEats smoke returned `ok=true`, `itemsSaved=1`, `memoryEvents=1`.
- `scripts/audit_worktree.ps1` now classifies these `24` deleted legacy tests/scripts as `TEST_COVERAGE_REBUILD`; they are not active import blockers.

Frontend snapshot gates:

```powershell
npm run test:unit
npm run build
```

## Rebuild Rules

1. Do not restore deleted tests wholesale; many target old module paths.
2. When touching diagnostic/session generation, add tests against `app.services.diagnostic.engine` and `app.services.diagnostic.session`.
3. When touching path/adaptive learning, first add narrow route/service tests for `app.api.path` and `app.services.path`.
4. When touching streaming endpoints, replace the old broad integration smoke with deterministic tests for `app.api.diagnostic_stream`, `app.api.lesson_stream`, and pipeline repair behavior.
5. When touching optimizer/batch tooling, add tests against `app.services.optimizer.optimizer.*` instead of old `app.optimizer.*`.
