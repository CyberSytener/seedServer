# NeoEats Public And Real Data Readiness - 2026-05-06

This note captures the current NeoEats runtime after the auth/tunnel repair pass. It is intentionally operational: what is live, what is still fallback/mock-backed, and what should become real data next.

## 2026-05-29 Live Scan Fallback Addendum

This pass tightened the mobile live scan failure path. The important user-level case is when a phone/browser cannot provide a camera stream or permission is denied: users should not be trapped in a scanner shell or see only a generic camera message.

Changes verified on 2026-05-29:

- Fullscreen live scan now surfaces inactive camera failures inside the scanner overlay, including `Camera not available`, the underlying browser/device message, `Try Camera Again`, and `Back to Photo Upload`.
- The scanner header distinguishes `Live scan paused` from `Live scan ready` and `Live scan active`, so users do not see an active-state label before camera access succeeds.
- The save button now communicates the active save mode: `No items`, `Save all`, or `Save pinned`.
- Overlay regression tests now cover top/bottom marker visibility and overflowing bbox clipping, in addition to landscape crop handling.

Verification:

- Frontend: `npm run test:unit` -> `16 passed`.
- Frontend: `npm run build` -> passed.
- Local mobile browser QA at `390x844` verified the no-camera live scan state and confirmed that `Back to Photo Upload` returns to the scan/upload screen.
- Public runtime was restored after Cloudflare `1033`: Docker Desktop/`seed_public` services were started, one `cloudflared` process is running, `https://api.neoeats.no/health` returns `ok=true`, `redis=true`, `db=true`, and `https://neoeats.no/` returns frontend HTML with the current `dist` asset.
- Public smoke: `.\scripts\smoke_public_neoeats.ps1` -> `ok=true`, user `smoke_58a314e1dd`, receipt `6d48bba6-cfae-4786-ad79-21255978205e`, `itemsSaved=1`, `memoryEvents=1`.

## 2026-05-28 Public Runtime Correction Addendum

This pass corrected a public runtime split-brain: Docker compose API was healthy internally with Redis, but public traffic on `127.0.0.1:8001` was being intercepted by a stale manual `python -m uvicorn app.main:app --port 8001` process. That made `https://api.neoeats.no/health` return `redis=false` even though `seed_public-redis-1` and `seed_public-api-1` were running.

Changes verified on 2026-05-28:

- Stopped the stale manual API process and force-recreated `seed_public-api-1` so Docker publishes `127.0.0.1:8001->8000/tcp`.
- Restarted Cloudflare Tunnel down to one `cloudflared` process.
- Confirmed `https://api.neoeats.no/health` returns `ok=true`, `redis=true`, `db=true`.
- Confirmed `https://neoeats.no/` and `https://www.neoeats.no/` return frontend HTML with the app root, not backend root JSON.
- Hardened `scripts/restore_public_runtime.ps1` so future restores fail on `redis=false`, verify frontend HTML, and stop stale manual `uvicorn app.main:app` listeners before recreating the compose API.
- Rechecked open registration through `https://neoeats.no/api/v1/auth/register`; public auth returns `accessToken`, authenticated profile calls accept the Bearer token, and CORS preflight from `https://neoeats.no` to `https://api.neoeats.no/api/v1/auth/register` returns `200` with credentials allowed.

Verification:

- `.\scripts\restore_public_runtime.ps1 -SkipDocker -SkipSmoke` -> public runtime healthy.
- `.\scripts\smoke_public_neoeats.ps1` -> `ok=true`, user `smoke_a827a7bf25`, receipt `e21123ff-9b7c-4777-a3a8-63b784dd5683`, `itemsSaved=1`, `memoryEvents=1`.

## 2026-05-28 Mobile Add-Food Trust Addendum

This pass focused on the first real user loop after registration: see pantry state, add food without confusion, and trust that product icons/freshness are real user data rather than presentation filler.

Changes verified on 2026-05-28:

- `Add Food` is now a clear mobile hub with three first actions: `Live scan`, `Type items`, and `Search foods`.
- Quick Add renders through a document-level portal so the fixed bottom navigation no longer intercepts the `Add 1 Item` button on mobile.
- Search-based quick add now closes after a successful save, returning the user to the pantry so the newly added item is immediately visible.
- Nonfunctional voice affordances were removed from Quick Add Type mode and the chat interaction bar; both now present text entry as the active interaction.
- Dashboard and pantry freshness fallback now treats missing freshness as fresh for non-expired saved items, preventing fresh pantry items from showing `0%`.
- Product icon normalization was tightened for early common staples: Butter, Olive Oil and Garlic now render specific icons instead of category fallbacks.
- Chat copy no longer exposes internal status names such as `DailyExpiryScanBlock`, `meal graph` or fake voice prompts; it presents `Pantry context` and text entry.
- Live scan copy no longer says active before camera access is actually available; inactive scan mode shows `Live scan ready`.

Verification:

- Frontend: `npm run build` -> passed.
- Frontend: `npm run test:unit` -> `14 passed`.
- Local mobile browser QA at `390x844` verified Dashboard freshness `100%`, visible product icons for Garlic, Olive Oil and Butter, Add Food hub copy, Quick Add/Search save without bottom-nav click-through, Chat copy without internal debug text, and Live Scan camera-required state with `Live scan ready`.

## 2026-05-27 User-Level Hardening Addendum

This pass focused on trust at early launch: remove visible placeholders, stop inventing order/store/payment state, and keep server data as the source of truth.

Changes verified on 2026-05-27:

- Orders now read backend order state only. The frontend no longer creates local pending orders after transient order-init failures, no longer merges local pending orders into server results, and surfaces order-load errors in the Orders screen.
- Order UI removed fake courier name, distance and live-map placeholders. ETA/tracking now says `Pending` or `Not yet` until the backend provides real courier assignment data.
- Explore was reframed from fake deals/community picks to `Recipes & Store`. Recipe opportunity cards show available/missing ingredient counts; store inventory cards show live quantity and last price only when returned by the catalog endpoint.
- Profile removed fake blockchain/zero-knowledge copy. Payment method type normalization maps legacy internal names to user-facing `mobile_pay`, `wallet`, `verified_card` and `card` labels while still showing no cards unless a real provider is linked.
- Optional dev pantry seeding now uses realistic local starter items instead of sci-fi demo products.
- Unused old demo components (`HeroSection`, quantum selection widgets, loading pulse, courier mock map and animated blob background) were removed after import search.
- Frontend product icon normalization now tests real Norwegian `br\u00f8d` input instead of mojibake test data.
- Live scan now also renders a persistent detected-product icon strip above the save controls. This gives users a stable place to confirm/stage recognized products on mobile even if floating camera markers overlap, crop near an edge or move between heartbeat scans.
- Home was reduced to practical kitchen and pantry surfaces; `Neural*` presentation components were replaced by kitchen/pantry components with lighter mobile animation.
- Registration UI now treats username, email and registration password as optional for early access. No email confirmation or invite step is required.
- The public order payment model no longer exposes `mock_decline`; test-triggered payment failure should not be part of the user-facing contract.
- Frontend route/modal/camera/cooking flows were code-split for mobile: the main production JS chunk dropped from about `1.16 MB` to about `469 kB` minified, and Chat, Cooking Mode, Fridge, Profile, Orders, Home, Quick Add, Live Scan and registration modal now load separately. The live scan hook no longer statically imports Capacitor Camera.

Verification:

- Frontend: `npm run build` -> passed without chunk or Capacitor camera warnings.
- Frontend: `npm run test:unit` -> `14 passed`.
- Backend: `pytest tests/unit/test_auth_open_registration.py tests/unit/test_neoeats_profile_routes.py tests/unit/test_neoeats_vision_geometry.py` -> `37 passed`.
- Local runtime checks: `POST http://127.0.0.1:5173/api/v1/auth/register` with a generated username returned `200` and an access token; in-app browser opened `http://127.0.0.1:5173/` and rendered the access screen without visible `Neural`, `Quantum`, `Cyber` or blockchain copy.

## 2026-05-26 Early-Launch Activation Addendum

The latest pass narrowed product work around the first beta-user loop instead of deepening commerce/order surfaces.

Changes verified on 2026-05-26:

- The early-launch activation loop is now explicit: registration -> first food added -> food rules -> recommendation request -> recipe feedback/save/cooking.
- Backend launch events are authenticated and user-scoped: `POST /api/v1/neoeats/launch/events` appends a compact event to `users.meta_json.neoeats_launch_events`, while `GET /api/v1/neoeats/launch/events` returns the current user's event list and summary.
- Admin launch review is available through `GET /api/v1/neoeats/launch/events/admin/summary` with `X-Admin-Key`; it reports event counts, user counts, activated user count and activation rate.
- Frontend records launch signals for registration, first/regular food add, live scan save, receipt confirmation, recommendation request, recommendation feedback, recipe save, cooking start/completion and dietary rule edits.
- Home now exposes a compact `Add food` / `Rules` / `Ask chef` strip, Quick Access prioritizes `Add Food`, the pantry empty state is clearer, and the hardcoded Orders notification dot is disabled.
- Launch telemetry is fire-and-forget: failed telemetry calls do not block registration, scanning, receipt confirmation, chat or cooking.

Verification:

- Backend: `tests\unit\test_neoeats_profile_routes.py` -> `18 passed`.
- Backend: NeoEats/auth/receipt/cooking/RAG subset -> `59 passed`.
- Frontend: `npm run test:unit` -> `14 passed`.
- Frontend: `npm run build` -> passed with known large chunk and Capacitor camera warnings.

Operational note: launch events are intentionally stored in user metadata for early beta speed. If this becomes cohort analytics, migrate them into an append-only analytics table or event stream before scale.

## 2026-05-25 Profile Dietary/RAG Addendum

The latest pass moved profile preferences from passive derived signals toward explicit user-editable data.

Changes verified on 2026-05-25:

- `ProfilePage` now exposes a `Dietary Profile` panel with editable chips for diet, allergies, avoided ingredients, goals and favorite cuisines.
- `GET/PATCH /api/v1/neoeats/profile` now returns and persists normalized `dietary_profile` data under `users.meta_json.neoeats_profile`.
- Dietary profile updates write `profile_dietary_updated` events into user-scoped RAG memory, gated by the new `profile` memory source.
- Profile-derived recommendation context now includes explicit diet/goals/cuisines/likes, and Chat sends real profile constraints instead of demo defaults such as `Low Carb`, `No Cilantro` or `time_of_day=dinner`.
- Admin-protected embedding operations now exist for scheduled/operator runs: `GET /api/v1/neoeats/memory/embeddings/admin/status` reports global event/user coverage and backlog, while `POST /api/v1/neoeats/memory/embeddings/admin/backfill` backfills pending/failed/unavailable events across bounded user batches with dry-run support.
- `scripts/backfill_neoeats_memory_embeddings.py` wraps that admin endpoint for cron, Windows Task Scheduler or operator shells.
- Public runtime was rebuilt and rechecked through the Cloudflare/Caddy tunnel.

Verification:

- Backend: expanded standard gate after dietary profile/RAG coverage -> `70 passed`.
- Backend: expanded standard gate after admin/global embedding backfill coverage -> `76 passed`.
- Backend targeted: `tests\unit\test_neoeats_rag_memory.py tests\unit\test_neoeats_profile_routes.py` -> `27 passed`.
- Frontend: `npm run test:unit -- --run src/utils/emoji.test.ts src/utils/visionOverlay.test.ts` -> `9 passed`.
- Frontend: `npm run build` -> passed with the known large chunk and Capacitor camera warnings.
- Public runtime: `scripts\restore_public_runtime.ps1` -> Docker/Caddy/Cloudflare checks OK and public smoke `ok=true`.
- Latest public restore after frontend dist rebuild: smoke user `smoke_bcffa4ef53`, receipt `edaa2eb7-775e-4913-b3bf-db4d370a0822`, `itemsSaved=1`, `memoryEvents=1`, `cloudflared` PID `248`.
- Latest public restore after admin/global embedding backfill rebuild: smoke user `smoke_8ce0d7c0f3`, receipt `5f930fc7-a4ec-45ec-9ef5-ec842466f4f3`, `itemsSaved=1`, `memoryEvents=1`, `cloudflared` PID `248`.
- Public admin embedding dry-run: `ok=true`, `backlog_event_count=41`, `backlog_user_count=31`, `embedding_coverage_pct=0.0`, `provider_available=false`, `reason=dry_run`; this confirms the operator endpoint is live while real embedding generation remains blocked by missing provider/key.
- Public dietary contract: user `dietary_smoke_2774fe4511` updated `vegetarian`, `peanut`, `cilantro`, `budget_friendly`, `quick_meals` and `japanese`; `/memory?query=peanut%20cilantro%20japanese%20budget` retrieved `profile_dietary_updated` event `83dfb002-d2cb-4a2a-bc10-550e715c16d4` from source `profile_preferences` through lexical fallback because the public embedding provider is not configured.

## 2026-05-23 Live Scan/Icon Addendum

The latest product stabilization passes focused on the trust problem around live scan product markers.

Changes verified on 2026-05-23:

- `front-neoeats-snapshot/src/utils/emoji.ts` now returns real emoji through Unicode escapes instead of mojibake-prone strings.
- Live scan labels call the resolver with backend `icon_key`, category and product name.
- Saved pantry rows can render icons from `metadata.icon_key`.
- Backend vision icon keys are more specific for cheese, poultry, potato and onion, while generic keys still cover dairy, vegetables, fruit, seafood, meat, grain and grocery fallback.
- Backend vision now dedupes overlapping same-product detections while preserving separate same-product detections when geometry shows different positions.
- `POST /api/v1/vision/analyze` now returns trust metadata: `dedupe_key`, `trust_level`, `review_required` and `duplicate_count` when applicable.
- Live scan UI surfaces `Good`, `Check` and `Review` states next to marker confidence, keeps uncertain products visually distinct and saves trust metadata into pantry item `metadata`.
- NeoEats memory now has user-facing controls: learning, RAG recall, personalization, per-source toggles, export and clear.
- Chat, pantry, scan, receipt and cooking memory writes now respect `neoeats_memory_controls`; chat retrieval also respects the RAG recall/personalization switches.
- RAG event retrieval now supports hybrid vector plus lexical ranking. Writes attempt provider-backed embeddings into `neoeats_user_memory_events.embedding`; retrieval uses pgvector similarity when available, then merges with token overlap, confidence, event type, subject and recency. If the provider or pgvector path is unavailable, retrieval falls back to lexical scoring.
- RAG memory stats now expose embedding status counts, ready count and coverage percentage; authenticated `POST /api/v1/neoeats/memory/embeddings/backfill` backfills current-user pending/failed/unavailable events when an embedding provider is active.
- Recipe recommendations now send accepted/rejected feedback to user-scoped RAG memory through authenticated `POST /api/v1/neoeats/recipes/feedback`; Profile memory controls include a dedicated `Recipe` source toggle.
- Recommendation cards now include quick rating/reason chips; feedback payloads can include `rating`, `reason_code` and `reason_tags` for price, effort, inventory-gap and taste-mismatch learning.
- Public UI registration completed through `https://neoeats.no/` without network error.
- Public Quick Add/Search rendered product icons correctly and the visible page text had no `рџ` mojibake markers.

Verification:

- Frontend: `npm run test:unit -- --run src/utils/emoji.test.ts src/utils/visionOverlay.test.ts` -> `9 passed`.
- Frontend: `npm run build` -> passed with the known large chunk warning.
- Backend: `python -m pytest -q tests\unit\test_neoeats_vision_geometry.py tests\unit\test_neoeats_inventory_extract.py tests\unit\test_product_normalize.py` -> `42 passed`.
- Backend: standard gate covering smoke/auth/security/RAG/receipt/vision -> `49 passed`.
- Backend: expanded standard gate after memory controls/profile coverage -> `58 passed`.
- Backend: expanded standard gate after provider-backed memory embeddings and hybrid retrieval coverage -> `60 passed`.
- Backend: expanded standard gate after embedding coverage/backfill coverage -> `65 passed`.
- Backend: expanded standard gate after recipe feedback memory events -> `68 passed`.
- Backend: expanded standard gate after recipe feedback rating/reason payloads -> `68 passed`.
- Security/docs audit: `python scripts\verify\verify_ci_security.py` -> OK; `scripts\audit_deleted_references.ps1` -> `NO_REFERENCES_FOUND 189`.
- Public runtime: `scripts\restore_public_runtime.ps1` -> Docker/Caddy/Cloudflare checks OK and public smoke `ok=true`.
- Public hybrid memory smoke after rebuild: `/api/v1/neoeats/memory` returned `memory_stats.by_embedding_status`; current public environment marked new memory events as `unavailable`, so retrieval correctly fell back to lexical mode until a real embedding provider/key is enabled.
- Public backfill smoke after rebuild: `POST /api/v1/neoeats/memory/embeddings/backfill` returned `embedding_provider_unavailable`, `attempted=0` and `skipped=5`; `/memory` returned `embedding_coverage_pct=0.0`, matching the current no-provider public environment.
- Public vision contract: overlapping Cheese metadata detections deduped to one response item with `duplicate_count=2`, `trust_level=trusted`; Tomato returned as `trust_level=check`.
- Public memory contract: default controls returned from `/profile`, `/memory/settings` updated RAG/source controls, `/memory` respected disabled retrieval, `/memory/export` returned `neoeats_memory_export_v1`, and `DELETE /memory` cleared current-user RAG events.
- Public recipe feedback contract: user `recipe_smoke_98799fd8d2` recorded `recipe_feedback_accepted` event `5f494665-10cd-42b3-bb56-4ff21e96c32c`; `/memory?query=salmon%20bowl` retrieved it from source `recipe_feedback` with lexical fallback because the public embedding provider is not configured.
- Public recipe reason contract: user `recipe_reason_0fb7e1d08e` recorded `recipe_feedback_rejected` event `a0374cf4-6868-48f3-a8e7-377414300a17` with `rating=2`, `reason_code=missing_too_much` and `reason_tags=[inventory_gap, shopping_needed]`; `/memory?query=ratatouille%20missing%20ingredients` retrieved it from source `recipe_feedback` with lexical fallback.

## 2026-05-19 Status Addendum

Latest system-level planning now lives in [SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19.md](SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19.md).

During the 2026-05-19 review, local implementation checks were healthy, but public availability was initially not:

- `https://neoeats.no/` returned Cloudflare `530`.
- `https://api.neoeats.no/health` returned Cloudflare `530`.
- `http://127.0.0.1:8001/health` did not respond.
- Docker Desktop was unavailable, so the `seed_public` compose stack could not be inspected at first.

Follow-up remediation on 2026-05-19:

- Docker Desktop was started.
- `seed_public` compose services were brought up and rebuilt after backend receipt-memory changes.
- `cloudflared` was started with `C:\Users\Exempel\.cloudflared\config.yml`.
- `https://neoeats.no/`, `https://www.neoeats.no/`, and `https://api.neoeats.no/health` returned healthy responses.
- Public registration worked.
- Public receipt confirmation through `POST /api/v1/vision/receipt/confirm` worked, receipt history returned the confirmed receipt, and RAG memory returned `receipt_item_confirmed`.

Current operational priority: add monitoring/service automation so tunnel/origin health does not depend on manual process startup.

Current product-data priority: add endpoint-level tests and continue into catalog-backed product identity. The frontend receipt review save path now calls backend `POST /api/v1/vision/receipt/confirm`.

## Current Routing

Local development:

- Frontend: `http://127.0.0.1:5173/`.
- Vite proxy: `/api/*` and `/v1/*` forward to `http://127.0.0.1:8001`.
- `front-neoeats-snapshot/.env.development` clears `VITE_API_BASE_URL` and `VITE_WS_URL`, so browser calls stay same-origin during local development and avoid public CORS.

Public:

- `https://neoeats.no` and `https://www.neoeats.no` go through Cloudflare Tunnel to local Caddy on `localhost:8080`.
- Caddy serves `front-neoeats-snapshot/dist` and proxies backend paths (`/api/*`, `/v1/*`, `/health`, `/ws*`, `/sse*`, docs and metrics paths) to `127.0.0.1:8001`.
- `https://api.neoeats.no` goes through Cloudflare Tunnel directly to `127.0.0.1:8001`.
- Public API CORS allows `https://neoeats.no` and `https://www.neoeats.no`; localhost is intentionally not allowed against the public API because local dev uses the Vite proxy.

Operational files:

- Actual tunnel config: `C:\Users\Exempel\.cloudflared\config.yml`.
- Repo tunnel template: `seed_server/cloudflared/config.example.yml`.
- Tunnel setup script: `seed_server/scripts/setup_cloudflare_tunnel.ps1`.
- Public API port: `PUBLIC_BIND_PORT=8001`.
- Public frontend/Caddy port: `FRONTEND_PUBLIC_PORT=8080`.

## Verified On 2026-05-06

- `http://127.0.0.1:5173/` returns the Vite app.
- `http://127.0.0.1:5173/api/v1/auth/register` returns `200` through Vite proxy.
- `https://neoeats.no/` returns frontend HTML, not backend JSON.
- `https://www.neoeats.no/` returns frontend HTML.
- `https://api.neoeats.no/health` returns backend health JSON.
- `https://neoeats.no/api/v1/auth/register` returns `200`.
- `https://neoeats.no/api/v1/auth/login` returns `200` for the newly registered test user.
- Authenticated `GET /api/v1/neoeats/dashboard` returns a real aggregate over pantry, receipts and order sagas, with source flags when a table is unavailable.
- Authenticated `GET/PATCH /api/v1/neoeats/profile` returns profile data derived from `users.meta_json`, NeoEats memory and real event aggregates, including editable `dietary_profile` fields for diet tags, allergies, avoided ingredients, goals and favorite cuisines.
- Authenticated `POST /api/v1/vision/analyze` returns stable `detection_id`, `icon_key`, confidence, category, bbox/center geometry and live-scan trust fields through public routing.
- `POST /api/v1/vision/analyze` with `confirm=true` persists confirmed scan items and writes `scan_item_confirmed` RAG memory events.
- Authenticated `GET /api/v1/neoeats/memory` returns structured profile memory, memory controls, memory stats and append-only user-scoped RAG events from `neoeats_user_memory_events`.
- RAG memory stats now include embedding status counts, and retrieved events include vector similarity/match reasons when a provider-backed embedding path is active.
- Authenticated `PATCH /api/v1/neoeats/memory/settings` updates learning/RAG/personalization/source controls.
- Authenticated `GET /api/v1/neoeats/memory/export` exports structured memory and RAG events for the current user.
- Authenticated `DELETE /api/v1/neoeats/memory` clears structured memory and current-user RAG events.
- Authenticated `POST /api/v1/neoeats/memory/embeddings/backfill` attempts current-user embedding backfill and returns provider availability, attempted/ready/unavailable/failed counts and updated memory stats.
- Admin `GET /api/v1/neoeats/memory/embeddings/admin/status` and `POST /api/v1/neoeats/memory/embeddings/admin/backfill` expose global embedding coverage/backlog and bounded all-user backfill through strict `X-Admin-Key`.
- Authenticated `PATCH /api/v1/neoeats/profile` records dietary edits as `profile_dietary_updated` memory events, respecting `memory_controls.sources.profile`.
- Authenticated `POST /api/v1/neoeats/recipes/feedback` records accepted/rejected recommendation signals as `recipe_feedback_accepted` or `recipe_feedback_rejected` events, respecting `memory_controls.sources.recipe`. The payload supports optional `rating`, `reason_code` and `reason_tags`.
- Authenticated `POST /api/v1/actions/invoke` chat receives `user_rag_memory_context` from prior scan/pantry events.
- CORS preflight from `https://neoeats.no` to `https://api.neoeats.no/api/v1/auth/register` returns `200` with credentials allowed.
- Mobile smoke at `390x844` verifies Dashboard/Profile load after registration with no horizontal overflow and no mock payment cards.

## Auth Status

Registration is now open-beta style:

- No email confirmation.
- No invite gate.
- Username, email and password may be omitted at registration; the backend generates a local user identity and the frontend only asks for a password if the user wants one for later sign-in.
- Collision handling suffixes usernames instead of blocking registration.
- Local browser development no longer talks directly to the public API, which was the main cause of `Network Error`.

## Mobile Status

The frontend remains mobile-first and Capacitor-ready. This pass tightened the auth modal for phones:

- Safe-area-aware top and bottom padding.
- Scrollable fixed overlay for short screens.
- Smaller mobile logo/title/padding, with desktop sizing preserved at `sm`.
- No public tunnel dependency for local mobile browser auth because `/api` is same-origin in Vite.

Remaining mobile risk:

- The production main chunk is now below the Vite warning threshold after page/modal/camera code-splitting. Remaining mobile performance work should focus on the Chat chunk and real-device camera latency.
- Browser QA is available for local smoke checks. The latest pass verified the unauthenticated local access screen; authenticated mobile UI should still be checked manually or with a browser session after explicit test-account submission approval.

## Product Outlook

Current product and engineering outlook is maintained in `docs/PROJECT_OUTLOOK_AND_NEXT_STEPS_2026-05-06.md`.

Short version: NeoEats should be the primary next product track. The strongest route is to make the real mobile loop reliable first: live scan, pantry, profile memory, receipt confirmation, recommendations, step-by-step cooking and feedback into RAG. The broader agent platform should support that flagship loop before being expanded as a standalone product.

## Stub And Fallback Map

Frontend:

- `src/services/mockFridgeAPI.ts` and `src/services/mockQuickAddAPI.ts` are legacy demo services. They are not imported by the active app and should be archived or deleted after confirming no external docs reference them.
- `src/context/UserContext.tsx` has been removed. `ProfilePage` now reads `GET /api/v1/neoeats/profile`; notification changes persist through `PATCH /api/v1/neoeats/profile`.
- `HomePage` now reads `GET /api/v1/neoeats/dashboard` for username, inventory pulse, order status and recommendation summaries instead of hardcoded dashboard identity.
- `HomePage`, `PantryShelf` and `UserInventoryContext` now normalize missing freshness for saved, non-expired items to avoid showing false `0%` freshness on early pantry data.
- `ProfilePage` now exposes AI Memory controls backed by `/api/v1/neoeats/memory/settings` and `/api/v1/neoeats/memory`.
- `ProfilePage` now exposes editable Dietary Profile chips backed by `GET/PATCH /api/v1/neoeats/profile`.
- `ChatPage`, `AIChatTab` and `src/hooks/useNeoEatsApi.ts` no longer inject demo taste/profile values; chat recommendation payloads use the authenticated dietary profile when present and otherwise send empty preference/constraint objects.
- `FinancialVault` no longer shows mock cards. Payment methods are empty until a real payment provider is linked.
- `src/hooks/useNeoEatsApi.ts` uses `localStorage` for capability flags and saved recipe recommendations. Order state is no longer synthesized from local pending/cached orders; server state is the source of truth.
- `src/hooks/useVisionScanner.ts` has `photo-fallback` mode for native mobile camera limitations. That is a device fallback, not fake product data.
- `src/hooks/useVisionScanner.ts` now uses server `detection_id`, `dedupe_key`, confidence trust fields and spatial buckets for stable overlay identity, review labeling and saved pantry metadata.
- `src/utils/emoji.ts` is the canonical frontend product-icon resolver; it prefers specific icon keys, then product names, then category/generic icon fallbacks.
- `src/utils/visionOverlay.ts` clamps object-cover marker coordinates into the visible camera container so icons stay visible on mobile crops.
- `QuickAddModal` is portal-rendered above the app shell so mobile bottom navigation cannot steal save clicks. Search and Type modes add real pantry items through the authenticated inventory flow; no active quick-add path uses the legacy mock services.
- `scripts/neoeats-smoke-server.mjs` is intentionally mock-only for local smoke flow tests.

Backend:

- `app/services/llm_engine.py` returns an empty vision result when the vision provider fails. This is a safe fallback because it does not invent detected products.
- `app/services/llm_engine.py` and `app/services/receipt_vision_engine.py` now fail closed for receipt extraction fallback: no fake `milk`/`bread` line items are returned when provider extraction is unavailable.
- `app/services/hybrid_recipes.py` is deterministic template matching over real inventory/store item inputs. Treat it as a rules fallback, not a final recommendation engine.
- `app/services/flavor_architect.py` has deterministic fallback plans when Gemini fails. These should stay as graceful degradation, but responses should expose degraded-provider status in telemetry.
- `app/services/neoeats_recipe_card.py` still uses heuristic nutrition/pricing for unknown ingredients. Replace this with a real nutrition/product catalog source before presenting nutritional claims as authoritative.
- `app/infrastructure/dev_helpers.py` seeds dev users/inventory only when explicitly enabled. Public mode disables dev seeding and test auth.
- `SEED_ENABLE_STUB` and `SEED_TEST_AUTH_MODE` are disabled in the public environment.

## Real Data Groundwork

Recommended next data contracts:

1. Profile and consent:
   - Existing first pass: `/api/v1/neoeats/profile` and `/api/v1/neoeats/dashboard`.
   - Editable dietary/allergy/avoidance/goal/cuisine fields are now stored on the user profile and feed RAG memory.
   - Next: add explicit privacy consent, allergy severity, source labels for learned-vs-explicit preferences and notification delivery channels.
   - Keep payment methods empty until a real payment adapter stores verified provider references.

2. User memory/RAG:
   - Current structured memory is stored in user metadata and merged into NeoEats chat context.
   - Append-only `neoeats_user_memory_events` now records chat, confirmed pantry/scan additions and cooking completions.
   - Chat now receives user-scoped RAG context from memory events before recommendation planning.
   - Memory controls now gate learning, RAG retrieval and individual event sources; export and clear endpoints are available.
   - Embedding generation and vector ranking are now wired through the active LLM engine when an embedding provider is configured; lexical retrieval remains the fallback.
   - Embedding coverage telemetry, user-scoped backfill and admin all-user backfill are now available through the memory endpoints.
   - Accepted/rejected recipe feedback events are now recorded from recommendation actions.
   - Rating/reason chips are now captured from recommendation cards and stored in RAG events.
   - Explicit dietary profile updates are now captured as `profile_dietary_updated` events and can be retrieved by RAG.
   - Next: wire the admin backfill script into an actual schedule and add production alerting for embedding provider failures.

3. Product and store catalog:
   - Treat `inventory_item` as the real product catalog root.
   - Add ingestion jobs for SKU, barcode/GTIN, brand, normalized name, category, unit, live price and availability.
   - Keep `storage_item` user-scoped and connect it to catalog items via stable product IDs.

4. Receipt pipeline:
   - Keep provider failure as `422 receipt_validation_failed` instead of fake data.
   - Add provider metadata: provider name, model, confidence, raw OCR text, validation errors, and retry/refinement status.
   - Only persist receipts through `/api/v1/vision/receipt/confirm` after user review.

5. Orders:
   - Server order state is now the only source of truth in the active frontend.
   - Add real courier/payment provider fields before showing ETA, distance, courier identity or payment-provider status.
   - Replace remaining saga-only order lifecycle assumptions with provider adapters and webhooks.

6. Cooking:
   - Record step progress, skipped steps, ingredient consumption, completion feedback and leftovers.
   - Feed those events back into memory retrieval and future recipe ranking.

## Recommended Next Development Order

1. Finish live scan device QA: same-product multi-instance tuning, low-confidence review UX, native camera fallback, lighting/rotation checks.
2. Wire `scripts/backfill_neoeats_memory_embeddings.py` into a real schedule and add alerting for embedding provider failures.
3. Split frontend bundle by route/feature, starting with camera, live scan and cooking mode.
4. Add a real product catalog ingestion path and map pantry items to stable product IDs.
5. Add receipt provider telemetry and a retry UI for `receipt_validation_failed`.
6. Add allergy severity and explicit consent/source labeling for profile-derived personalization.
7. Turn order cache into a sync layer over real server order events.
