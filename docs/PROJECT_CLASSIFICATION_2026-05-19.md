# Project Classification - 2026-05-19

This document marks project areas as active, legacy, demo/mock, generated, archive or unknown. It is a cleanup guide, not a deletion script.

## Labels

- `ACTIVE`: used by the current backend/frontend runtime.
- `LEGACY`: old or transitional code that may still be imported, but should not receive new feature work.
- `DEMO_MOCK`: smoke/demo/mock-only code.
- `GENERATED`: build output, logs, local DBs, runtime files.
- `ARCHIVE`: historical reports, snapshots and old phase material.
- `UNKNOWN`: needs import/reference verification before moving or deleting.

## Active Backend Areas

| Path | Label | Notes |
| --- | --- | --- |
| `app/main.py` | ACTIVE | FastAPI application assembly. |
| `app/api/auth_routes.py` | ACTIVE | Open beta registration/login and auth facade. |
| `app/api/inventory_orders_vision_routes.py` | ACTIVE | NeoEats inventory, orders, live vision and cooking completion. |
| `app/api/receipts.py` | ACTIVE | Receipt analysis, confirmation and history. |
| `app/api/neoeats_profile_routes.py` | ACTIVE | Dashboard, profile and memory endpoint. |
| `app/api/actions_saga_routes.py` | ACTIVE | NeoEats chat/action invocation and RAG context wiring. |
| `app/api/neoeats_chat.py` | ACTIVE | NeoEats chat handler. |
| `app/services/neoeats_rag_memory.py` | ACTIVE | Append-only user memory and retrieval. |
| `app/services/receipt_vision_engine.py` | ACTIVE | Receipt extraction and fail-closed validation. |
| `app/services/product_normalize.py` | ACTIVE | Pantry/product normalization helper. |
| `app/services/pantry_normalizer.py` | ACTIVE | Canonical product and quantity normalization. |
| `app/services/neoeats_recipe_card.py` | ACTIVE | Recipe card and cooking plan logic. |
| `app/infrastructure/db/neoeats_db.py` | ACTIVE | Runtime NeoEats DB compatibility layer. Move schema ownership to Alembic. |
| `app/infrastructure/*` | ACTIVE | DB, Redis, middleware, CORS, logging, lifespan. |
| `app/core/agent/*` | ACTIVE | Agent platform base. |
| `app/core/realtime/*` | ACTIVE | Realtime/saga platform base. |
| `app/models/realtime/*` | ACTIVE | Realtime action/message/schema models. |
| `app/infrastructure/realtime/*` | ACTIVE | Realtime integration adapters and infrastructure wiring. |
| `scripts/run_worker.py` | ACTIVE | Public worker command. |
| `scripts/run_scheduler.py` | ACTIVE | Public scheduler command. |
| `scripts/audit_worktree.ps1` | ACTIVE_TOOLING | Reproducible git status and cleanup inventory helper. |
| `scripts/audit_deleted_references.ps1` | ACTIVE_TOOLING | Deleted code/config reference audit helper. |
| `scripts/restore_public_runtime.ps1` | ACTIVE_TOOLING | One-command public runtime restore/check wrapper. |
| `scripts/smoke_public_neoeats.ps1` | ACTIVE_TOOLING | Public NeoEats smoke check for frontend, API, registration, receipt confirmation and memory. |
| `scripts/verify/verify_ci_security.py` | ACTIVE_TOOLING | Current CI/security baseline verifier. |
| `.github/workflows/*.yml` | ACTIVE_CI | Current workflow set. Uses `pip install -e ".[dev]"` for runtime-compatible CI installs where the project imports app code. |
| `docker-compose.public.yml` | ACTIVE | Public runtime stack. |
| `Caddyfile` | ACTIVE | Public frontend/API local origin routing. |
| `cloudflared/config.example.yml` | ACTIVE_TEMPLATE | Template only. Actual config lives in user profile. |

## Active Frontend Areas

| Path | Label | Notes |
| --- | --- | --- |
| `front-neoeats-snapshot/src/App.tsx` | ACTIVE | Mobile-first SPA shell. |
| `front-neoeats-snapshot/src/pages/HomePage.tsx` | ACTIVE | Dashboard page. |
| `front-neoeats-snapshot/src/pages/FridgePage.tsx` | ACTIVE | Pantry, scan, receipt review and recipe entrypoint. |
| `front-neoeats-snapshot/src/pages/ChatPage.tsx` | ACTIVE | AI chat and cooking interactions. |
| `front-neoeats-snapshot/src/pages/ProfilePage.tsx` | ACTIVE | Profile, notifications, receipts and payment placeholder. |
| `front-neoeats-snapshot/src/hooks/useNeoEatsApi.ts` | ACTIVE | Main API hook layer. |
| `front-neoeats-snapshot/src/hooks/useVisionScanner.ts` | ACTIVE | Live camera/vision hook. |
| `front-neoeats-snapshot/src/context/UserInventoryContext.tsx` | ACTIVE | Server-backed pantry context. |
| `front-neoeats-snapshot/src/components/ReceiptReviewModal.tsx` | ACTIVE | Receipt confirmation review UI. |
| `front-neoeats-snapshot/src/components/quickadd/LiveVisionScanner.tsx` | ACTIVE | Live scan UI. |
| `front-neoeats-snapshot/src/utils/visionOverlay.ts` | ACTIVE | Overlay geometry helpers. |

## Demo And Mock Areas

| Path | Label | Action |
| --- | --- | --- |
| `front-neoeats-snapshot/scripts/neoeats-smoke-server.mjs` | DEMO_MOCK | Keep as local smoke fixture. |
| `front-neoeats-snapshot/scripts/neoeats-smoke-flow.mjs` | DEMO_MOCK | Keep as local smoke fixture. |
| `front-neoeats-snapshot/src/services/mockFridgeAPI.ts` | REMOVED_DEMO_MOCK | Removed after import search found no active references. |
| `front-neoeats-snapshot/src/services/mockQuickAddAPI.ts` | REMOVED_DEMO_MOCK | Removed after import search found no active references. |
| `SEED_ENABLE_STUB` provider paths | DEMO_MOCK | Keep for test/dev, disabled in public mode. |

## Removed Or Replaced Areas

| Path | Label | Action |
| --- | --- | --- |
| `app/realtime/*` | REPLACED_OLD_LAYER | No active import references after 2026-05-20 audit. Current runtime uses `app/core/realtime/*`, `app/models/realtime/*`, and `app/infrastructure/realtime/*`. Keep deletion in dedicated cleanup branch. |
| `app/optimizer/*` | REPLACED_OLD_LAYER | No active import references after 2026-05-20 audit. Current runtime uses `app/services/optimizer/optimizer/*`. Keep deletion in dedicated cleanup branch. |
| old flat `app/*.py` compatibility modules | REPLACED_OLD_LAYER | No active import references after 2026-05-20 audit. Current runtime uses `app/api/*`, `app/core/*`, `app/services/*`, and `app/infrastructure/*` packages. |
| old `app/pipeline/*` package | REPLACED_OLD_LAYER | No active import references after 2026-05-20 audit. Current runtime uses `app/services/pipeline/pipeline/*`. |
| `app/monitoring/metrics.py` | REPLACED_OLD_LAYER | No active import references after 2026-05-20 audit. Current runtime uses infrastructure/core monitoring modules. |
| `app/ab_testing.py` | REPLACED_OLD_LAYER | Rewired to `app/core/ab_testing.py`. |
| `app/alerting.py` | REPLACED_OLD_LAYER | Rewired to `app/infrastructure/monitoring/alerting.py`. |
| `app/diagnostic_engine.py` | REPLACED_OLD_LAYER | Rewired to `app/services/diagnostic/engine.py`. |
| `app/learning_path.py` | REPLACED_OLD_LAYER | Rewired to `app/services/path/learning.py`. |
| `app/learning_plan.py` | REPLACED_OLD_LAYER | Rewired to `app/services/learning_plan.py`. |
| `app/slo_monitor.py` | REPLACED_OLD_LAYER | Rewired to `app/infrastructure/monitoring/slo_monitor.py`. |
| `app/worker_redis.py` | REPLACED_OLD_LAYER | Rewired to `app/infrastructure/redis/worker.py`. |

## Generated Or Runtime Files

| Path | Label | Action |
| --- | --- | --- |
| `front-neoeats-snapshot/dist/` | GENERATED | Public Caddy serves it. Do not commit unless intentionally versioning deploy artifacts. |
| `front-neoeats-snapshot/build/` | GENERATED | Ignore/archive. |
| `front-neoeats-snapshot/node_modules/` | GENERATED | Ignore. |
| `seed_server/logs/` | GENERATED | Ignore except intentional runbook examples. |
| `seed_server/logs/public/` | GENERATED_RUNTIME | Current cloudflared runtime logs. Keep locally while tunnel startup is manual. |
| `seed_server/seed.db` | GENERATED | Local runtime DB. Do not treat as canonical data. |
| `seed_server/*.db` | GENERATED | Local test/runtime artifacts unless explicitly fixture-named. |
| `seed_server/.pytest_cache/` | GENERATED | Ignore. |
| `seed_server/.vite/` | GENERATED | Ignore. |
| `seed_server/.tmp_*` | GENERATED | Remove or ignore after confirming no fixture use. |
| `seed_server/.tmp_openclaw_extract/` | GENERATED | Local extraction output. Ignored; not a product source. |
| `seed_server/.seed_artifacts/` | GENERATED | Local artifact output. Ignored; not a product source. |
| `seed_server/scripts/_*.py` | GENERATED_SCRATCH | Local exploratory scripts. Ignored; review manually before promoting any script to active tooling. |
| `seed_server/scripts/bench_*.txt` | GENERATED_SCRATCH | Local benchmark output. Ignored. |
| `seed_server/scripts/*_results.txt` | GENERATED_SCRATCH | Local benchmark/result output. Ignored. |
| `seed_server/scripts/startup_trace.txt` | GENERATED_SCRATCH | Local trace output. Ignored. |
| `seed_server/scripts/detour_dist.txt` | GENERATED_SCRATCH | Local benchmark output. Ignored. |
| `seed_server/reports/baseline/` | UNKNOWN_GENERATED | Verify before archive. |

## Archive Candidates

| Path | Label | Action |
| --- | --- | --- |
| root-level old `*_REPORT.md` files | ARCHIVE | Move to `_archive` if not linked from current docs. |
| root-level old `PHASE_*`, `FINAL_*`, `SESSION_*` docs | ARCHIVE | Move to `_archive` after link check. |
| `seed_server.snapshot*.zip` | ARCHIVE | Already outside active backend root. Keep outside git. |
| `front-neoeats-snapshot.zip` | ARCHIVE | Already outside active frontend working path. |
| `docs/*2026-02*`, `docs/*2026-03*` | ARCHIVE | Historical unless referenced as current. |

## Legacy Or Lower-Priority Product Areas

| Area | Label | Notes |
| --- | --- | --- |
| Learning/career/photo APIs | LEGACY_ACTIVE | Platform demos. Keep stable, do not expand before NeoEats beta. |
| Marketplace/tenant governance | LEGACY_ACTIVE | Useful platform surface, not current product focus. |
| `saga-console/` | ACTIVE_INTERNAL | Internal orchestration console. Needs tests before public-facing claims. |
| Payments/orders provider depth | FUTURE | Do not deepen until product catalog, receipt confirmation tests and cooking analytics are reliable. |

## Cleanup Order

1. Run `powershell -ExecutionPolicy Bypass -File scripts\audit_worktree.ps1`.
2. Add or verify `.gitignore` rules for generated files.
3. Use `rg` to confirm mock/demo services are not imported by active app paths.
4. Move archive candidates to `_archive` in a dedicated cleanup branch.
5. Keep documentation updates in a separate commit.
6. Keep NeoEats receipt/catalog code changes separate from archive cleanup.
7. Decide whether `front-neoeats-snapshot` becomes a separate repository or a formal monorepo package.

## Do Not Delete Yet

- Any `app/api/*` router without route/import introspection.
- Any `app/core/realtime/*` or `app/core/agent/*` code.
- Any migration file.
- Any current docs listed in `SOURCE_OF_TRUTH.md`.
- Any smoke script used by CI or documented runbooks.
