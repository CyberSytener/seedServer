# System Analysis And Development Plan - 2026-05-19

This is the current working analysis for `seed_server/` and the separate `front-neoeats-snapshot/` app. It supersedes the 2026-05-06 outlook for planning purposes, while older reports remain useful as historical context.

## Executive Summary

The system is a broad AI/backend platform with NeoEats as the clearest product surface. The local codebase is functional: the FastAPI app imports, the route graph registers, focused backend tests pass, the NeoEats frontend builds, and the local NeoEats smoke loop can verify pantry staging, recipe recommendation and cooking completion.

The main issue on 2026-05-19 is not that the product loop is empty. It is that release trust is uneven:

- Local NeoEats core flows are green.
- Public runtime returned Cloudflare `530` during the initial review, then was restored in the follow-up pass by starting Docker Desktop, `seed_public` compose services and `cloudflared`.
- Public runtime is now reachable, but it still depends on manually managed Docker/Caddy/cloudflared processes until service startup and monitoring are automated.
- The repository remains extremely dirty, so every new feature risks being mixed with archive cleanup and generated artifacts.
- Some real-data groundwork exists, but it is split between runtime table ensures and migrations; this must be consolidated before production data grows.

Strategic recommendation: continue treating NeoEats as the flagship product. Keep public availability reproducible, make repository hygiene explainable, then finish the real-data NeoEats loop in this order: live scan real-device trust, vector-backed user memory with controls, product catalog and receipt telemetry, cooking session analytics, then payment/order provider integrations.

2026-05-25 update: the memory/profile track has moved forward. NeoEats now has editable profile dietary fields, profile-source RAG events, recipe feedback learning, memory controls/export/clear, provider-backed embedding attempts with hybrid vector/lexical retrieval, embedding coverage telemetry, current-user backfill and admin/global backfill endpoints with a scheduler-friendly CLI wrapper. The remaining RAG work is now operational hardening: wire the backfill script into an actual schedule, add production provider monitoring, explicit consent/source labels, allergy severity and recommendation explanations.

2026-05-26 update: the product focus has been narrowed for early launch. Instead of deepening payments/orders or broad analytics, NeoEats now tracks one activation loop: registration -> add food -> set food rules -> request a recommendation -> save/cook/leave feedback. The backend exposes launch telemetry through `/api/v1/neoeats/launch/events` and admin `/api/v1/neoeats/launch/events/admin/summary`; the frontend records those events without blocking user actions and surfaces a compact Home CTA strip for `Add food`, `Rules` and `Ask chef`.

## Verified On 2026-05-19

Backend:

```powershell
python -m pytest -q tests\unit\test_neoeats_rag_memory.py tests\unit\test_neoeats_vision_geometry.py tests\unit\test_neoeats_profile_routes.py tests\unit\test_auth_open_registration.py tests\unit\test_receipt_fallback_no_fake_items.py tests\unit\test_neoeats_cooking_complete.py tests\unit\test_neoeats_cooking_plan.py
```

Result: `29 passed`.

2026-05-26 targeted verification for the early-launch pass:

- `python -m pytest tests\unit\test_neoeats_profile_routes.py -q` -> `18 passed`.
- `python -m pytest -q tests\unit\test_neoeats_rag_memory.py tests\unit\test_neoeats_vision_geometry.py tests\unit\test_neoeats_profile_routes.py tests\unit\test_auth_open_registration.py tests\unit\test_receipt_fallback_no_fake_items.py tests\unit\test_neoeats_cooking_complete.py tests\unit\test_neoeats_cooking_plan.py` -> `59 passed`.
- `front-neoeats-snapshot`: `npm run test:unit` -> `14 passed`.
- `front-neoeats-snapshot`: `npm run build` -> passed with known large chunk and Capacitor camera warnings.

```powershell
python -m pytest -q tests\test_ci_smoke.py tests\test_auth_verify_user_context.py tests\unit\test_security_hardening.py tests\unit\test_llm_router_openai_regression.py
```

Result: `28 passed`.

Route introspection:

- `create_test_app()` registered `233` routes in test mode.
- Saga orchestrator and WebSocket gateway were disabled in that introspection run because Postgres/JWT secrets were not configured for the local test environment.

Frontend:

```powershell
npm run test:unit
```

Result: `9 passed`.

```powershell
npm run build
```

Result: passed. Remaining warnings:

- main JS chunk is still large: about `1,147 kB` minified and `324 kB` gzip.
- `@capacitor/camera` is both statically and dynamically imported, so Vite cannot split it cleanly.

Smoke flow:

```powershell
npm run smoke:server -- --port 5174
npm run smoke:flow
```

Result: passed after the smoke server was started. The flow verified login, inventory extraction, pantry add, recommendation, embedded cooking plan and cooking completion.

Public runtime checks:

- Initial check: `https://neoeats.no/` and `https://api.neoeats.no/health` returned Cloudflare `530`.
- Remediation: Docker Desktop was started, `seed_public` compose services were brought up, and `cloudflared` was started against `C:\Users\Exempel\.cloudflared\config.yml`.
- After remediation: `https://neoeats.no/` returned frontend HTML.
- After remediation: `https://www.neoeats.no/` returned frontend HTML.
- After remediation: `https://api.neoeats.no/health` returned `{"ok":true,"redis":true,"db":true,"mode":"normal"}`.
- Public registration through `https://neoeats.no/api/v1/auth/register` returned `200`.
- Public receipt confirmation through `https://neoeats.no/api/v1/vision/receipt/confirm` returned `items_saved=1`.
- Public receipt history returned the confirmed receipt.
- Public memory retrieval returned a `receipt_item_confirmed` event for the confirmed receipt item.

Conclusion: local implementation checks are healthy; public tunnel/origin availability was restored, but it needs monitoring because the failure mode was process availability rather than code.

Follow-up artifacts added:

- `docs/STATE_MARK_2026-05-19.md`
- `docs/PROJECT_CLASSIFICATION_2026-05-19.md`
- `docs/CLEANUP_INVENTORY_2026-05-19.md`
- `docs/VERIFY_IMPORTS_AUDIT_2026-05-20.md`
- `docs/PUBLIC_RUNTIME_RUNBOOK_2026-05-19.md`
- `scripts/audit_deleted_references.ps1`
- `scripts/audit_worktree.ps1`
- `scripts/restore_public_runtime.ps1`
- `scripts/smoke_public_neoeats.ps1`
- `tests/unit/test_receipt_confirm_routes.py`

## Repository State

Observed under `seed_server/`:

- `3712` total git status entries from `scripts/audit_worktree.ps1`.
- `3151` tracked deletions.
- `88` modified files.
- `473` untracked files.

Current cleanup buckets:

- `COMMIT_NOW`: `50`
- `VERIFY_IMPORTS`: `616`
- `DELETE_IN_CLEANUP_BRANCH`: `2667`
- `ARCHIVE_REVIEW`: `289`
- `MANUAL_REVIEW`: `90`

Focused import cleanup result:

- `scripts/audit_deleted_references.ps1` checked `189` deleted code/config files.
- `189` have no active references.
- `0` remain as review candidates.
- Runtime imports were fixed for deleted top-level modules that still had active callers.
- Old `app/realtime/*` files are now cleanup candidates; active realtime code resolves through `app/core/realtime/*`, `app/models/realtime/*`, and `app/infrastructure/realtime/*`.

The separate `front-neoeats-snapshot/` directory is not a git repository.

Implication: the current tree is workable for local development, but it is not release-clean. Before a production beta or a large feature branch, split the dirty state into intentional groups: docs, NeoEats feature work, archive cleanup, generated artifacts and local runtime files.

## System Map

Backend entrypoint:

- `app/main.py` builds the FastAPI app, core SQLite DB, Redis clients, queue hub, SSE broker, LLM providers, NeoEats engines, realtime infrastructure and routers.

Backend layers:

- API: `app/api/*`
- Core: `app/core/*`
- Services: `app/services/*`
- Infrastructure: `app/infrastructure/*`
- Migrations: `migrations/versions/*`
- Workers/schedulers: `scripts/run_worker.py`, `scripts/run_scheduler.py`

NeoEats backend surface:

- Auth: `app/api/auth_routes.py`
- Dashboard/profile/memory: `app/api/neoeats_profile_routes.py`
- Inventory/orders/live vision/cooking complete: `app/api/inventory_orders_vision_routes.py`
- Receipt analyze/confirm/history: `app/api/receipts.py`
- Chat/RAG invocation: `app/api/actions_saga_routes.py`, `app/api/neoeats_chat.py`
- RAG memory: `app/services/neoeats_rag_memory.py`
- Receipt extraction: `app/services/receipt_vision_engine.py`
- Product/pantry normalization: `app/services/product_normalize.py`, `app/services/pantry_normalizer.py`
- Recipe/cooking: `app/services/neoeats_recipe_card.py`, `app/api/cooking.py`

Frontend surface:

- `front-neoeats-snapshot/src/App.tsx` is a mobile-first single-page app with local page navigation.
- Active pages: Home, Chat, Explore, Orders, Profile, Fridge.
- Active data hooks live mostly in `src/hooks/useNeoEatsApi.ts` and `src/hooks/useVisionScanner.ts`.
- `src/context/UserInventoryContext.tsx` is backed by live inventory APIs.
- Legacy demo services still exist: `src/services/mockFridgeAPI.ts` and `src/services/mockQuickAddAPI.ts`; they are not the current data source but should be archived or deleted after one final import check.

## What Is Real Today

- Open beta registration exists and does not require email confirmation or invites.
- Dashboard/profile use authenticated backend endpoints.
- Live scan response contract includes stable `detection_id`, `icon_key`, confidence, category and geometry.
- Frontend live scan marker math clamps product icons into the visible camera container.
- Confirmed scan, pantry, chat, profile dietary edits, recipe feedback and cooking signals are written as append-only `neoeats_user_memory_events`.
- Chat can retrieve user-scoped RAG memory context and now receives explicit dietary/profile constraints instead of demo taste defaults.
- Receipt extraction fails closed instead of inventing fake grocery items.
- Backend has `/api/v1/vision/receipt/confirm`, which persists receipts, updates catalog-like `inventory_item` rows, updates user pantry storage and writes ledger events.
- Frontend has receipt review UI and a confirm modal for scanned food.
- Cooking completion updates pantry quantities and records memory events.

## Main Gaps

### P0: Public Availability

The public product was unreachable through Cloudflare at the start of the 2026-05-19 review, then recovered after starting Docker Desktop, the public compose stack and `cloudflared`.

Required next actions:

- Add a simple external health monitor for `neoeats.no`, `www.neoeats.no` and `api.neoeats.no`.
- Add a local runbook for starting Docker Desktop, `seed_public`, Caddy and `cloudflared`.
- Consider running `cloudflared` as a Windows service instead of a manually started process.
- Keep `scripts/smoke_public_neoeats.ps1` as the reproducible public smoke check.

### P0: Product Catalog And Receipt Confirmation

Backend receipt confirmation exists. In the follow-up pass on 2026-05-19, the frontend receipt review path was wired to `/api/v1/vision/receipt/confirm`, and backend receipt confirmation now records `receipt_item_confirmed` RAG memory events.

Required next actions:

- Add tests proving receipt confirmation creates receipt history and updates pantry.
- Promote product identity from heuristic `match_id` to a stable catalog product ID where available.

### P0: Repository Hygiene

The dirty tree is still too large for confident feature delivery. The project needs a short branch hygiene pass before deeper work.

Required next actions:

- Decide what the tracked deletions mean.
- Move generated runtime files into ignore rules or archive.
- Keep documentation changes separate from code features.
- Consider making `front-neoeats-snapshot` its own repository or bringing it into a deliberate monorepo layout.

### P1: RAG Memory Is Useful But Still Needs Operational Hardening

The current memory layer is append-only and user-scoped with user-facing controls, export/clear endpoints, recipe feedback events and explicit dietary profile events. It attempts provider-backed embeddings and uses hybrid vector plus lexical retrieval when the embedding path is available; public runtime currently falls back to lexical retrieval because no embedding provider/key is configured.

Required next actions:

- Wire `scripts/backfill_neoeats_memory_embeddings.py` into Windows Task Scheduler, cron or a dedicated container job.
- Add production alerts for embedding provider unavailable/error states and low coverage using the admin status endpoint.
- Add learned-fact inspection with explicit source labels: user-entered, receipt-backed, scan-backed, cooking-backed, recipe-feedback-backed.
- Add allergy severity and consent UX before using profile dietary data in stronger recommendation constraints.
- Add recommendation explanations that show which memory signals affected the answer.

### P1: Database Schema Governance

Important NeoEats tables are ensured at runtime in `get_neoeats_db()`, while some older tables are in Alembic migrations. Runtime ensure is convenient, but production data needs migrations as the source of truth.

Required next actions:

- Add Alembic migrations for `receipts`, storage item extensions and `neoeats_user_memory_events`.
- Decide whether `inventory_item` is the canonical catalog root or whether a dedicated product catalog table is needed.
- Stop relying on startup DDL for production schema evolution after migration parity is reached.

### P1: Mobile Performance And Test Surface

The NeoEats frontend is mobile-first in UX, but not yet mobile-optimized in bundle shape. Test coverage is concentrated in utilities, not page workflows.

Required next actions:

- Code-split camera/live scan/cooking routes.
- Remove static `@capacitor/camera` import from the initial bundle path.
- Add React-level tests for auth modal, dashboard/profile loading, receipt review and scan confirmation.
- Add real-device QA for camera permissions, low light, rotation, duplicate products and low-confidence icons.

### P1: Optional Router Error Policy

`app/infrastructure/router_registration.py` documents an ImportError-only suppression policy, but the agent router block still catches broad `Exception`. That can hide real startup failures.

Required next actions:

- Narrow the agent router exception handling.
- Add a regression test that non-import startup failures are not swallowed.

## Product Prospects

### NeoEats

Prospect: high.

NeoEats has the clearest path to a useful product: pantry, receipt scan, live scan, recommendations, cooking, memory and eventual ordering all reinforce the same user loop. The product should not expand into payment/order/courier depth until product data and receipt confirmation are reliable.

### Agent Platform

Prospect: high as enabling infrastructure, medium as standalone product right now.

Agent sessions, saga orchestration, tool permissions and LLM routing are valuable, but they should support NeoEats first. The platform can become visible later through automation, grocery planning, meal-prep agents and operational dashboards.

### Saga Console

Prospect: medium.

It is useful for internal orchestration and debugging, but it needs tests and clearer product ownership before it becomes a public-facing surface.

### Learning/Career/Marketplace/Photo

Prospect: medium later, low priority now.

They show platform range, but they fragment focus. Keep them stable, but do not use them as the main development track until NeoEats is public-beta reliable.

## General Development Plan

### Horizon 0: Restore Trust, 1-3 Days

Goal: make the system reachable and the worktree understandable.

- Restore public `neoeats.no` and `api.neoeats.no` health.
- Add a deployment runbook entry for Cloudflare `530`.
- Capture current Docker/Caddy/cloudflared process checks in docs.
- Split dirty tree into intentional groups.
- Keep all new product work on a branch with an explainable diff.

Exit criteria:

- `https://neoeats.no/` serves frontend HTML.
- `https://api.neoeats.no/health` returns backend health JSON.
- `git status --short` is either clean or documented by category.

### Horizon 1: NeoEats Real-Data Loop, 1-2 Weeks

Goal: every user-facing pantry/receipt/scan action writes real, inspectable data.

- Keep the early-launch activation loop measurable before expanding scope: registration, first food add, live scan/receipt confirmation, food rules, recommendation request, recipe save/feedback and cooking completion.
- Use `GET /api/v1/neoeats/launch/events/admin/summary` during beta reviews to find drop-off before adding new large surfaces.
- Receipt review is wired to `/api/v1/vision/receipt/confirm`; keep expanding telemetry and retry/refine UX.
- Receipt memory events and receipt history coverage exist; keep adding provider metadata tests.
- Build first product catalog ingestion path for barcode/GTIN, brand, normalized name, category, unit, nutrition, allergens and source metadata.
- Link `storage_item` rows to catalog products.
- Show data source labels: catalog-backed, receipt-backed, scan-estimated, user-entered.

Exit criteria:

- Admin launch summary shows user counts for registration, first food, recommendation request, feedback/save and cooking completion.
- Receipt confirmation creates receipt history and pantry updates through the dedicated endpoint.
- Pantry items can reference stable product/catalog IDs.
- No nutrition/pricing claim is shown without a data-source label.

### Horizon 2: Real RAG And Personalization, 2-4 Weeks

Goal: the assistant learns transparently and safely.

- Keep embeddings/vector retrieval active where a provider is configured and automate backfill/alerting where it is not.
- Use user-scoped vector/lexical retrieval with recency, confidence and event-type boosts as the default recommendation context.
- Expand Profile memory inspection from controls/export into readable learned-fact cards.
- Record accepted/rejected recipes and dietary edits already; add substituted ingredients and deeper cooking outcomes.
- Add explanation cards: why this recipe/order recommendation was suggested.

Exit criteria:

- Users can see, clear and pause memory.
- Recommendations cite concrete user signals.
- Tests prove user memory does not leak across users.

### Horizon 3: Cooking Analytics, 3-6 Weeks

Goal: make cooking mode a feedback engine, not only a recipe display.

- Persist cooking sessions, per-step progress, timers, skipped steps and completion status.
- Track consumed quantity, leftovers and substitutions.
- Feed cooking outcomes back into recipe ranking.
- Add mobile QA for cooking mode on narrow screens.

Exit criteria:

- Cooking completion updates pantry, memory and recommendation ranking.
- Analytics can answer which recipes are started, completed, abandoned and repeated.

### Horizon 4: Payments, Orders And Provider Integrations, 6-10 Weeks

Goal: deepen commerce only after data trust is in place.

- Define order state machine and provider adapter interfaces.
- Add payment provider tokenization/reference storage, not raw card storage.
- Add provider webhooks and reconciliation.
- Make frontend pending order cache a sync/recovery layer over server truth.
- Add order/payment observability and rollback paths.

Exit criteria:

- Orders and payment states are provider-backed.
- Webhooks reconcile state changes.
- UI can explain pending, failed and confirmed states without local-only assumptions.

## Recommended Backlog Order

1. Run early beta sessions against the measured loop: register, add food, rules, recommendation, save/feedback/cook.
2. Use launch event admin summary to identify the first major drop-off.
3. Keep real-device live scan QA as the next trust gate: duplicate products, low light, rotation, permissions and native camera fallback.
4. Clean or categorize repository state enough that active NeoEats changes are reviewable.
5. Wire the admin embedding backfill script into a real schedule and add production monitoring for RAG coverage/provider failures.
6. Create Alembic migrations for current NeoEats runtime tables.
7. Add product catalog ingestion and product ID linking.
8. Split frontend bundle by camera/live-scan/cooking.
9. Add receipt provider telemetry and retry/refine UI.
10. Expand Profile memory inspection, consent/source labels and allergy severity.
11. Persist cooking sessions and step analytics.
12. Only then expand payment/orders/courier integrations.

## KPIs

Product:

- Registration success rate.
- First pantry item added rate.
- Live scan confirmation rate.
- Receipt confirmation completion rate.
- Recommendation acceptance rate.
- Cooking session completion rate.
- Repeat usage within 7 days.

Quality:

- Public uptime for `neoeats.no` and `api.neoeats.no`.
- API p95 latency for dashboard, profile, inventory, vision and chat.
- Vision provider failure rate.
- Receipt validation failure rate.
- Memory retrieval latency and cross-user isolation test coverage.
- Frontend bundle size and mobile load time.

## Current Bottom Line

The project has a credible product core. The next development phase should be disciplined: restore public availability, stabilize the repo, connect receipt confirmation to real data, build the catalog, make memory transparent, then deepen cooking analytics and payments. NeoEats should remain the organizing product until the public grocery-to-cooking loop is reliable end to end.
