# Verify Imports Audit - 2026-05-20

This document records the focused pass over deleted tracked files in code-sensitive areas: `.github/`, `app/`, `tests/`, `scripts/`, and `migrations/`.

## Tools

Run from `seed_server/`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\audit_deleted_references.ps1
powershell -ExecutionPolicy Bypass -File scripts\audit_worktree.ps1
```

`scripts/audit_deleted_references.ps1` searches active code/config roots for literal references to deleted tracked files. It also checks missing-target relative imports such as `from . import old_module` when the resolved relative module does not exist. It intentionally excludes historical docs so stale reports do not look like runtime dependencies.

## Reference Audit Result

Snapshot after import fixes and active bucket split on 2026-05-23:

- deleted code/config files checked: `189`
- no active references found: `189`
- remaining referenced candidates: `0`
- old broad `VERIFY_IMPORTS` bucket: retired after classification
- deleted files left in import-risk buckets: `0`
- active review buckets replacing it: `NEOEATS_PUBLIC_BETA`, `PLATFORM_APP_REVIEW`, `AGENT_PLATFORM_REVIEW`, `INFRASTRUCTURE_REVIEW`, `REALTIME_PLATFORM_REVIEW`, `ACTIVE_CODE_REVIEW`, `TEST_REVIEW`, `SCRIPT_REVIEW`, `MIGRATION_REVIEW`

Runtime import fixes completed:

| Old deleted import | Current import |
| --- | --- |
| `app.ab_testing` | `app.core.ab_testing` |
| `app.alerting` | `app.infrastructure.monitoring.alerting` |
| `app.diagnostic_engine` / `from app import diagnostic_engine` | `app.services.diagnostic.engine` |
| `app.learning_path` | `app.services.path.learning` |
| `from app import learning_plan` | `app.services.learning_plan` |
| `app.slo_monitor` | `app.infrastructure.monitoring.slo_monitor` |
| `app.worker_redis` | `app.infrastructure.redis.worker` |
| `app.realtime.repositories.job_automation_repository` | local `JobAutomationRepositoryService` protocol in `app.infrastructure.realtime.integrations.inbox_polling_service` |
| missing relative `diagnostic_engine` import in `app.core.ab_testing` | `app.services.diagnostic.engine` |
| missing relative `persona_prompts` import in `app.services.diagnostic.engine` | `app.core.persona_prompts` |
| missing relative `validators.repair` import in `app.services.pipeline.pipeline.steps` | `app.core.validators.validators.repair` |
| missing relative `util` / `diagnostic_session` imports in `app.services.learning_plan` | `app.core.util` and `app.services.diagnostic.session` |
| invalid lesson repair fallback output | `app.core.validators.validators.repair` schema-valid repair/padding |

Files updated for those import fixes:

- `app/core/ab_testing.py`
- `app/core/validators/validators/repair.py`
- `app/api/admin_routes.py`
- `app/api/diagnostics_routes.py`
- `app/api/lessons_routes.py`
- `app/api/learning_feedback_monitoring_routes.py`
- `app/infrastructure/realtime/integrations/inbox_polling_service.py`
- `app/services/diagnostic/engine.py`
- `app/services/learning_plan.py`
- `app/services/pipeline/pipeline/steps.py`
- `scripts/diagnostics/check_production_ready.py`

## Remaining Referenced Candidates

The focused audit currently reports no referenced deleted files in active code/config roots.

Important interpretation:

- `app/models.py` is a deleted flat-file predecessor; `app/models/` is now an active package namespace.
- `app/router.py` was a deleted module; `app.router` in tests is a FastAPI object property, not a module import.
- old `app/realtime/*` files are no longer active import targets; current runtime uses `app/core/realtime/*` and `app/models/realtime/*`.
- stale documentation examples in active realtime/optimizer docs were updated to current package paths.
- relative import traps are now checked by resolving the target package path; valid local imports such as `from .feature_flags` are ignored when the target file/package exists.
- ignored local scratch files such as `scripts/_*.py`, `.seed_artifacts/`, and `.tmp_openclaw_extract/` are excluded from active reference checks.
- deleted old code/config paths with no references are classified as `REPLACED_CLEANUP_READY`.
- deleted legacy tests are classified as `TEST_COVERAGE_REBUILD`, not import risk.
- remaining modified/untracked active entries are classified by owner/risk in `docs/ACTIVE_REVIEW_BUCKETS_2026-05-20.md`.

## CI Cleanup

Current workflow files under `.github/workflows/` were verified as parseable YAML.

Install commands were updated to use the canonical package metadata instead of the incomplete `requirements.txt` runtime subset:

```bash
pip install -e ".[dev]"
```

Updated workflow set:

- `full-tests.yml`
- `smoke-tests.yml`
- `integration-tests.yml`
- `lint.yml`
- `route-registration-sanity.yml`
- `real-llm-smoke.yml`
- `simulation-tests.yml`
- `security-gates.yml`
- `server-intel-drift.yml`

Additional CI verification update:

- `scripts/verify/verify_ci_security.py` now checks the current workflow names and uses ASCII-safe output on Windows terminals.

Realtime documentation/path update:

- active `app/core/realtime/job_matching/*` examples now use `app.core.realtime.job_matching`.
- active `app/core/realtime/optimized/*` examples now use `app.core.realtime.optimized`.
- optimizer docs under `app/services/optimizer/optimizer/` now use `app.services.optimizer.optimizer.*`.
- old `app.llm_client_async` examples in active docs now point to `app.infrastructure.llm.client`.

## Verification

Passed after this pass:

```powershell
python scripts\verify\verify_ci_security.py
python -m pytest -q tests\test_ci_smoke.py tests\test_auth_verify_user_context.py tests\unit\test_security_hardening.py tests\unit\test_llm_router_openai_regression.py
python -m pytest -q tests\unit\realtime\test_engine_bridge_imports.py tests\unit\realtime\test_action_router.py tests\unit\realtime\test_contracts.py tests\test_ci_smoke.py
```

Also verified:

- all `.github/workflows/*.yml` files parse with PyYAML
- old direct runtime imports for the deleted top-level modules no longer match active code search
- deleted-reference audit returns `NO_REFERENCES_FOUND` for all `189` deleted code/config files checked
- local scratch benchmark artifacts, verified replaced code/config deletions, deleted legacy tests, and current cleanup docs/fixes were moved out of the old `VERIFY_IMPORTS` classification by ignore/audit rules. The remaining active app worktree entries are now split into `NEOEATS_PUBLIC_BETA` (`12`), `PLATFORM_APP_REVIEW` (`61`), `INFRASTRUCTURE_REVIEW` (`25`), `AGENT_PLATFORM_REVIEW` (`15`), `REALTIME_PLATFORM_REVIEW` (`2`), and `ACTIVE_CODE_REVIEW` (`4`), alongside `TEST_REVIEW` (`108`), `SCRIPT_REVIEW` (`84`), and `MIGRATION_REVIEW` (`11`).
- import checks passed for `app.core.ab_testing`, `app.services.diagnostic.engine`, `app.services.pipeline.pipeline.steps`, and `app.services.learning_plan`.
- lesson pipeline cost-accounting regression now passes after repair hardening.

## Next Slice

Continue reducing active review buckets in this order:

1. Verify `NEOEATS_PUBLIC_BETA` with focused NeoEats tests and public smoke.
2. Verify `MIGRATION_REVIEW` ordering and public DB compatibility.
3. Pair `TEST_REVIEW` files with the code slices they cover.
4. Keep `AGENT_PLATFORM_REVIEW` and `REALTIME_PLATFORM_REVIEW` separate from NeoEats beta.
5. Promote or archive `SCRIPT_REVIEW` entries based on docs/CI/public-runtime references.
