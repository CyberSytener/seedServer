# Active Review Buckets - 2026-05-20

This document replaces the broad `VERIFY_IMPORTS` bucket for the remaining modified/untracked active worktree entries. Deleted files are now handled separately by `REPLACED_CLEANUP_READY`, `TEST_COVERAGE_REBUILD`, `DELETE_IN_CLEANUP_BRANCH`, `ARCHIVE_REVIEW`, and `MANUAL_REVIEW`.

Last reviewed: 2026-05-26

## Current Bucket Snapshot

From `scripts/audit_worktree.ps1` on 2026-05-23:

| Bucket | Total | Deleted | Modified | Untracked | Meaning |
| --- | ---: | ---: | ---: | ---: | --- |
| `PLATFORM_APP_REVIEW` | 61 | 0 | 13 | 48 | Generic app/API/service/core code outside the NeoEats public-beta slice. |
| `INFRASTRUCTURE_REVIEW` | 25 | 0 | 6 | 19 | App wiring, DB/Redis/monitoring/CORS/lifespan/runtime infrastructure. |
| `AGENT_PLATFORM_REVIEW` | 15 | 0 | 8 | 7 | Agent/session/billing/console/marketplace/saga platform surface. |
| `NEOEATS_PUBLIC_BETA` | 12 | 0 | 0 | 12 | NeoEats public-beta routers, RAG/catalog/receipt/inventory/cooking support. |
| `ACTIVE_CODE_REVIEW` | 4 | 0 | 0 | 4 | Remaining active app directories that need one more owner decision. |
| `REALTIME_PLATFORM_REVIEW` | 2 | 0 | 0 | 2 | Current realtime package replacements. |
| `TEST_REVIEW` | 108 | 0 | 15 | 93 | Active tests and test support files. |
| `SCRIPT_REVIEW` | 84 | 0 | 24 | 60 | Active scripts and runbooks that need promote/archive/ignore decisions. |
| `MIGRATION_REVIEW` | 11 | 0 | 1 | 10 | Alembic/SQL migration files requiring ordering and runtime DB review. |

## NeoEats Public Beta

Current product slice:

- `app/api/cooking.py`
- `app/api/inventory_orders_vision_routes.py`
- `app/api/neoeats_chat.py`
- `app/api/neoeats_profile_routes.py`
- `app/api/receipts.py`
- `app/catalog/`
- `app/core/embeddings.py`
- `app/core/neoeats_blocks.py`
- `app/infrastructure/db/neoeats_db.py`
- `app/infrastructure/db/pgvector_store.py`
- `app/infrastructure/db/seed_catalog.py`
- `app/infrastructure/embeddings/`

Review rule:

1. Keep this slice as the first product commit group after docs/tooling.
2. Verify with NeoEats focused tests plus public smoke before deepening orders/payments/analytics.
3. Treat `app/catalog/` as mixed product/platform catalog until file-level ownership is split.

Related frontend snapshot files outside the backend git repository:

- `front-neoeats-snapshot/src/hooks/useVisionScanner.ts`
- `front-neoeats-snapshot/src/components/quickadd/LiveVisionScanner.tsx`
- `front-neoeats-snapshot/src/context/UserInventoryContext.tsx`
- `front-neoeats-snapshot/src/pages/HomePage.tsx`
- `front-neoeats-snapshot/src/pages/ChatPage.tsx`
- `front-neoeats-snapshot/src/pages/FridgePage.tsx`
- `front-neoeats-snapshot/src/pages/ProfilePage.tsx`
- `front-neoeats-snapshot/src/components/BetaAccessModal.tsx`
- `front-neoeats-snapshot/src/utils/visionOverlay.ts`
- `front-neoeats-snapshot/src/utils/emoji.ts`
- `front-neoeats-snapshot/src/utils/emoji.test.ts`

Latest product checks through 2026-05-26:

- Product icon rendering was stabilized by replacing mojibake-prone emoji strings with a canonical resolver that combines backend `icon_key`, product names and category fallback.
- Backend vision now emits more specific icon keys for cheese, poultry, potato and onion.
- Backend live scan now dedupes overlapping same-product detections and returns `dedupe_key`, `trust_level`, `review_required` and `duplicate_count` for frontend review UX and saved pantry metadata.
- NeoEats memory controls/export/clear now live in the profile slice and gate chat, pantry, scan, receipt, cooking and recipe feedback memory events; recipe feedback now includes rating/reason chips for price, effort, inventory-gap and taste-mismatch learning; RAG memory also has provider-backed embedding writes, hybrid vector/lexical retrieval, embedding coverage telemetry, current-user backfill, admin/global backfill endpoints and `scripts/backfill_neoeats_memory_embeddings.py` for scheduled/operator runs, with lexical fallback.
- Profile dietary fields now live in the profile slice: editable diet/allergy/avoidance/goal/cuisine chips persist through `/api/v1/neoeats/profile`, write `profile_dietary_updated` RAG events through the `profile` source gate, and feed Chat recommendation constraints without demo taste defaults.
- Early-launch activation telemetry now lives in `app/api/neoeats_profile_routes.py`: authenticated user event append/read endpoints plus an admin summary endpoint for registration, first food, scan/receipt, recommendation, feedback/save and cooking signals.
- Frontend early-launch instrumentation records those signals without blocking user actions, and Home now prioritizes the first beta loop with `Add food`, `Rules` and `Ask chef`.
- Public UI registration, Quick Add/Search icon rendering and the public `vision/analyze` trust contract were verified on `https://neoeats.no/`.

## Platform App Review

Largest generic app areas:

- `app/api/*`: router split and NeoEats/platform API surface.
- `app/core/*`: auth, LLM, realtime, validators, module registry and shared domain blocks.
- `app/infrastructure/*`: app wiring, DB adapters, CORS, lifespan, Redis, monitoring and realtime adapters.
- `app/services/*`: NeoEats, diagnostic, lesson, optimizer, path, pipeline, marketplace and photo service packages.
- `app/models/*`: package replacement for old flat `app/models.py`.

Review rule:

1. Keep generic agent/realtime/platform changes separate from NeoEats product changes when possible.
2. Do not commit platform route split without route registration tests.
3. Do not classify an active router/service as cleanup-only until route registration and focused tests pass.

## Agent And Realtime Review

Agent platform slice:

- `app/core/agent/*`
- `app/api/agent_routes.py`
- `app/api/agent_integration.py`
- `app/api/console/`
- `app/api/marketplace_routes.py`
- `app/api/saga_blueprints.py`
- `app/billing_service.py`
- `app/agent_sandbox_worker.py`

Realtime slice:

- `app/core/realtime/`
- `app/infrastructure/realtime/`

Review rule:

1. Keep agent/realtime contracts and tests paired together.
2. Do not mix this slice with NeoEats receipt/live-scan work.
3. Keep old deleted `app/realtime/*` in `REPLACED_CLEANUP_READY`; current runtime lives under `app/core/realtime/*`, `app/models/realtime/*`, and `app/infrastructure/realtime/*`.

## Infrastructure Review

Current infra slice:

- `app/infrastructure/*`
- `app/main.py`
- `app/settings.py`
- `app/dependencies.py`
- `app/dependency_check.py`
- `app/key_management.py`
- `app/worker_main.py`

Review rule:

1. Keep public runtime wiring and CORS/lifespan changes separate from feature changes.
2. Pair DB adapter changes with migration review.
3. Keep `restore_public_runtime.ps1` and `smoke_public_neoeats.ps1` as release gates while Cloudflare startup remains operationally sensitive.

## Test Review

Largest test areas:

- `tests/unit/*`: active unit coverage for auth, agent, NeoEats, realtime, marketplace, catalog, security and validators.
- `tests/integration/*`: active integration flows and real-LLM/simulation smokes.
- `tests/support/*`, `tests/conftest.py`: shared fixtures.

Review rule:

1. Keep tests paired with the code slice they verify.
2. Do not restore deleted legacy tests wholesale; use `docs/TEST_COVERAGE_CLEANUP_2026-05-20.md` for rebuild guidance.
3. Before removing or archiving a test file, prove replacement coverage with a targeted pytest command.

## Script Review

Largest script areas:

- diagnostics helpers under `scripts/diagnostics/*`.
- current public runtime scripts: `restore_public_runtime.ps1`, `smoke_public_neoeats.ps1`, `run_public.ps1`, `setup_cloudflare_tunnel.ps1`.
- validation helpers: `validate_catalog.py`, `validate_modules.py`, `verify_schema_exports.py`, `verify_server_intel.py`.
- exploratory bot/simulation helpers that should either move to docs/tools or remain ignored scratch.

Review rule:

1. Promote only scripts referenced by docs, CI, or public runtime runbooks.
2. Archive one-off debug scripts after confirming no docs or CI references.
3. Keep public NeoEats recovery/smoke scripts in the stabilization commit.

## Migration Review

Current migration review set:

- `migrations/env.py`
- `migrations/add_saga_correlation_id.sql`
- `migrations/versions/002_add_saga_indexes.py`
- `migrations/versions/003_add_pgvector_embeddings.py`
- `migrations/versions/004_add_job_leads_user_skills.py`
- `migrations/versions/005_add_stock_levels.py`
- `migrations/versions/006_add_inventory_ledger.py`
- `migrations/versions/007_create_saga_tables.py`
- `migrations/versions/008_add_vision_intake_storage.py`
- `migrations/versions/009_add_hot_offer_tables.py`
- `migrations/versions/010_add_webhook_subscriptions.py`

Review rule:

1. Confirm migration ordering and downgrade behavior before committing.
2. Keep NeoEats inventory/receipt migrations separate from saga/realtime migrations when possible.
3. Do not rely on `app/infrastructure/db/neoeats_db.py` as the long-term schema owner; schema ownership should move into Alembic.

## Next Review Order

1. `NEOEATS_PUBLIC_BETA`: verify product code and focused tests.
2. `MIGRATION_REVIEW`: verify migration order and public DB compatibility.
3. `TEST_REVIEW`: pair active tests with the split code commits.
4. `AGENT_PLATFORM_REVIEW` and `REALTIME_PLATFORM_REVIEW`: keep platform contracts separate from NeoEats beta.
5. `SCRIPT_REVIEW`: promote current runtime/CI scripts, archive or ignore exploratory helpers.
