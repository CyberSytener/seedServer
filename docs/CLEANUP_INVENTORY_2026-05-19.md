# Cleanup Inventory - 2026-05-19

This document is the practical cleanup map for the current repository state. It should be used before broad feature work so cleanup, docs, generated artifacts and product code do not get mixed together.

## Reproducible Audit

Run from `seed_server/`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\audit_worktree.ps1
```

Current audited snapshot on 2026-05-23:

- total git status entries: `3604`
- tracked deletions: `3151`
- modified entries: `88`
- untracked entries: `365`

Top dirty areas:

| Area | Total | Deleted | Modified | Untracked | Handling |
| --- | ---: | ---: | ---: | ---: | --- |
| `node_modules` | 1775 | 1775 | 0 | 0 | Treat as tracked/generated cleanup. Do not restore blindly. |
| `test_path` | 393 | 393 | 0 | 0 | Historical/generated test output candidate. Cleanup branch only. |
| `app` | 284 | 158 | 27 | 99 | Needs import and route-level ownership review before cleanup. |
| `scripts` | 94 | 4 | 26 | 64 | Mixed active scripts and reviewable helpers after ignoring local scratch outputs. Review file by file. |
| `test_artifacts` | 187 | 187 | 0 | 0 | Generated artifact cleanup candidate. |
| `optimizer_logs` | 180 | 180 | 0 | 0 | Generated artifact cleanup candidate. |
| `tests` | 137 | 20 | 15 | 102 | Keep product test changes separate from cleanup. |
| `reports` | 66 | 66 | 0 | 0 | Historical/generated report cleanup candidate. |
| `docs` | 38 | 0 | 7 | 31 | Current docs plus new state docs. Commit separately. |

Cleanup bucket summary from `scripts/audit_worktree.ps1`:

| Bucket | Total | Deleted | Modified | Untracked | Meaning |
| --- | ---: | ---: | ---: | ---: | --- |
| `DELETE_IN_CLEANUP_BRANCH` | 2667 | 2667 | 0 | 0 | Tracked generated/test artifact deletions; handle in a dedicated cleanup branch. |
| `ARCHIVE_REVIEW` | 290 | 222 | 11 | 57 | Historical docs/reports or old planning files; move/archive after link check. |
| `REPLACED_CLEANUP_READY` | 165 | 165 | 0 | 0 | Deleted old code/config layers with no active references after the deleted-reference audit. |
| `TEST_REVIEW` | 108 | 0 | 15 | 93 | Active tests and test support files. |
| `MANUAL_REVIEW` | 88 | 73 | 4 | 11 | Config/security/miscellaneous files that need explicit human review. |
| `SCRIPT_REVIEW` | 84 | 0 | 24 | 60 | Active scripts and runbooks that need promote/archive/ignore decisions. |
| `PLATFORM_APP_REVIEW` | 61 | 0 | 13 | 48 | Generic app/API/service/core code outside the NeoEats public-beta slice. |
| `COMMIT_NOW` | 48 | 0 | 6 | 42 | Current stabilization docs, public runtime tooling and CI fixes. |
| `INFRASTRUCTURE_REVIEW` | 25 | 0 | 6 | 19 | App wiring, DB/Redis/monitoring/CORS/lifespan/runtime infrastructure. |
| `TEST_COVERAGE_REBUILD` | 24 | 24 | 0 | 0 | Deleted legacy tests/scripts that need targeted replacement coverage only when those legacy surfaces receive new work. |
| `AGENT_PLATFORM_REVIEW` | 15 | 0 | 8 | 7 | Agent/session/billing/console/marketplace/saga platform surface. |
| `NEOEATS_PUBLIC_BETA` | 12 | 0 | 0 | 12 | NeoEats public-beta routers, RAG/catalog/receipt/inventory/cooking support. |
| `MIGRATION_REVIEW` | 11 | 0 | 1 | 10 | Alembic/SQL migration files requiring ordering and runtime DB review. |
| `ACTIVE_CODE_REVIEW` | 4 | 0 | 0 | 4 | Remaining active app directories that need one more owner decision. |
| `REALTIME_PLATFORM_REVIEW` | 2 | 0 | 0 | 2 | Current realtime package replacements. |

## Cleanup Already Performed

Safe ignored/generated files removed during this pass:

- `.tmp_any.jpg`
- `.tmp_food.jpg`
- `.tmp_neoeats_index.html`
- `.vite/`
- old `logs/bot/` simulation logs
- old `logs/sim_output_v*.txt`

Tooling added:

- `scripts/audit_deleted_references.ps1` - checks deleted tracked code/config files for active references.
- `scripts/audit_worktree.ps1` - reproducible dirty tree and cleanup bucket report.
- `scripts/restore_public_runtime.ps1` - one-command public runtime restore/check wrapper for Docker, Caddy, Cloudflare Tunnel and optional public smoke.
- `scripts/smoke_public_neoeats.ps1` - public registration/receipt/memory smoke.

Scratch/noise classification added:

- `.tmp_openclaw_extract/`
- `.seed_artifacts/`
- `scripts/_*.py`
- `scripts/bench_*.txt`
- `scripts/*_results.txt`
- `scripts/startup_trace.txt`
- `scripts/detour_dist.txt`

These files are ignored or classified as local generated scratch material. They were not deleted by this pass.

Import and review progress:

- `scripts/audit_deleted_references.ps1` now reports `189/189` deleted code/config files with no active references.
- The deleted-reference audit now also checks missing-target relative imports, so `from . import old_module` style mistakes are caught when the resolved module no longer exists.
- The audit excludes ignored local scratch files such as `scripts/_*.py`, `.seed_artifacts/`, and `.tmp_openclaw_extract/` from active reference checks.
- stale runtime imports for deleted top-level modules were rewired to current packages.
- `app/infrastructure/realtime/integrations/inbox_polling_service.py` no longer imports deleted `app.realtime.repositories.*`.
- fixed missing-target relative imports in `app/core/ab_testing.py`, `app/services/diagnostic/engine.py`, `app/services/pipeline/pipeline/steps.py`, and `app/services/learning_plan.py`.
- fixed lesson pipeline repair validation for common LLM outputs: normalized skill aliases such as `word_order`, read fallback values from `grading`, generated missing `lessonId`, and made padding stubs schema-valid.
- active realtime/optimizer docs now use current package paths (`app.core.realtime.*`, `app.models.realtime.*`, `app.services.optimizer.optimizer.*`).
- deleted old `.github`, `app/realtime/*`, `app/optimizer/*`, flat `app/*.py`, old `app/pipeline/*`, and old `app/monitoring/metrics.py` paths are now classified as `REPLACED_CLEANUP_READY`.
- deleted legacy tests and old script tests are now classified as `TEST_COVERAGE_REBUILD`.
- the old broad `VERIFY_IMPORTS` bucket has been retired; remaining modified/untracked active entries are now split into product/platform buckets, including `NEOEATS_PUBLIC_BETA`, `PLATFORM_APP_REVIEW`, `AGENT_PLATFORM_REVIEW`, `INFRASTRUCTURE_REVIEW`, `REALTIME_PLATFORM_REVIEW`, `TEST_REVIEW`, `SCRIPT_REVIEW`, and `MIGRATION_REVIEW`.

NeoEats frontend cleanup:

- Removed unused `front-neoeats-snapshot/src/services/mockFridgeAPI.ts`.
- Removed unused `front-neoeats-snapshot/src/services/mockQuickAddAPI.ts`.
- Verified no active references with `rg`.
- Verified `npm run test:unit` and `npm run build` after removal.

Left intentionally:

- `logs/public/cloudflared.err.log`
- `logs/public/cloudflared.out.log`

Reason: these are the current public tunnel recovery logs. They can be deleted after public tunnel startup is automated and monitoring exists.

## Ignore Rules Added

`.gitignore` now covers:

- `logs/`
- `logs/public/`
- generated benchmark/test directories such as `test_artifacts/`, `test_path/`, `optimizer_logs/`, `mode_test_logs/`, `response_capture_logs/`, `extended_test_logs/`, `dynamic_test_logs/`, `final_test_logs/`
- `multi_phase_*/`
- `prompt_test_results/`
- local extraction/artifact directories such as `.tmp_openclaw_extract/` and `.seed_artifacts/`
- local scratch benchmark scripts/results under `scripts/_*.py`, `scripts/bench_*.txt`, and `scripts/*_results.txt`
- generated report/hash scratch files

These rules prevent new local generated artifacts from expanding the dirty worktree. They do not resolve already tracked deletions; those require an intentional cleanup commit.

## Classification Rules

Use these buckets for the next cleanup pass:

- `COMMIT_NOW`: current docs, smoke scripts, tooling and CI fixes.
- `NEOEATS_PUBLIC_BETA`: NeoEats public-beta routers, RAG/catalog/receipt/inventory/cooking support.
- `PLATFORM_APP_REVIEW`: generic app/API/service/core code outside the NeoEats public-beta slice.
- `AGENT_PLATFORM_REVIEW`: agent/session/billing/console/marketplace/saga platform surface.
- `INFRASTRUCTURE_REVIEW`: app wiring, DB/Redis/monitoring/CORS/lifespan/runtime infrastructure.
- `REALTIME_PLATFORM_REVIEW`: current realtime package replacements.
- `ACTIVE_CODE_REVIEW`: remaining active app directories requiring one more owner decision.
- `TEST_REVIEW`: active tests and fixtures requiring pairing with code slices.
- `SCRIPT_REVIEW`: active scripts requiring promote/archive/ignore decisions.
- `MIGRATION_REVIEW`: migration files requiring ordering and runtime DB review.
- `IGNORE_ONLY`: local runtime output, caches, tunnel logs, generated build/test output.
- `ARCHIVE`: historical phase reports and obsolete root-level audit files that are no longer current.
- `REPLACED_CLEANUP_READY`: deleted old code/config paths with no active references and known replacements.
- `TEST_COVERAGE_REBUILD`: deleted legacy tests that should be rebuilt as focused tests before those surfaces receive new feature work.
- `DELETE_IN_CLEANUP_BRANCH`: generated tracked deletions after confirming they are not fixtures.

## Recommended Commit Split

1. Documentation and state markers:
   - `README.md`
   - `SOURCE_OF_TRUTH.md`
   - `PROBLEMS_AND_TASKS.md`
   - `docs/*2026-05-19.md`
   - `docs/guides/DOCUMENTATION_INDEX.md`

2. NeoEats receipt/RAG product code:
   - receipt confirmation frontend wiring
   - receipt confirmation backend memory events
   - focused unit tests

3. Tooling and hygiene:
   - `.gitignore`
   - `.github/workflows/*.yml`
   - `scripts/audit_worktree.ps1`
   - `scripts/audit_deleted_references.ps1`
   - `scripts/restore_public_runtime.ps1`
   - `scripts/smoke_public_neoeats.ps1`
   - `scripts/verify/verify_ci_security.py`
   - `Caddyfile`
   - `docker-compose.public.yml`
   - `.env.public.example`
   - `cloudflared/config.example.yml`

4. CI/import stabilization:
   - `app/api/admin_routes.py`
   - `app/api/diagnostics_routes.py`
   - `app/api/lessons_routes.py`
   - `app/api/learning_feedback_monitoring_routes.py`
   - `scripts/diagnostics/check_production_ready.py`

5. Archive/generated cleanup:
   - tracked deletions under generated/test artifact/report directories
   - old phase report moves

Do not combine item 5 with feature work.

## Next Debugging Gate

Before the next large NeoEats feature:

1. Run `scripts\audit_worktree.ps1`.
2. Run `scripts\restore_public_runtime.ps1 -SkipDocker -SkipTunnel -SkipSmoke` for a non-invasive public runtime check.
3. Run `scripts\smoke_public_neoeats.ps1`.
4. Confirm `git status --short` can be explained by the commit buckets above.
5. Keep public runtime logs only while tunnel startup remains manual.
6. Move from cleanup to product work in this order:
   - live scan real-device trust and duplicate icon handling
   - true vector-backed user RAG memory with consent/clear controls
   - product catalog and receipt telemetry
   - orders/payments/cooking analytics
