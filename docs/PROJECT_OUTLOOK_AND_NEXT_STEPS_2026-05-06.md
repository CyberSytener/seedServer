# Project Outlook And Next Steps - 2026-05-06

This document is the current product and engineering outlook after the NeoEats public routing, open registration, real Dashboard/Profile data, live scan hardening, first RAG memory event pass, and mobile smoke verification pass on 2026-05-06.

## 2026-05-19 Update

Latest system analysis and planning now lives in [SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19.md](SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19.md).

The strategic direction is unchanged: NeoEats should remain the flagship product track. The priority order is now sharper:

1. Restore public tunnel/origin health; Cloudflare `530` was observed for `neoeats.no` and `api.neoeats.no` during the 2026-05-19 review.
2. Stabilize the dirty repository state.
3. Connect receipt review to `/api/v1/vision/receipt/confirm`.
4. Build catalog-backed product data.
5. Add transparent RAG memory controls and vector retrieval.
6. Deepen cooking analytics.
7. Only then expand payments/orders/provider integrations.

## 2026-05-25 Update

The RAG/profile track is no longer only pending roadmap work. NeoEats now has profile memory controls, export/clear, recipe feedback events, provider-backed embedding attempts with hybrid vector/lexical retrieval, embedding coverage/backfill endpoints, admin/global backfill endpoints with a scheduler-friendly CLI wrapper, and editable dietary profile fields that write `profile_dietary_updated` memory events. Chat recommendations now use those explicit profile constraints and no longer inject demo taste defaults.

Updated near-term priority:

1. Finish real-device live scan QA and trust tuning.
2. Wire the admin embedding backfill script into a real schedule plus provider failure monitoring.
3. Build catalog-backed product data and receipt provider telemetry.
4. Split the mobile frontend bundle by camera/live-scan/cooking routes.
5. Add consent/source labels, allergy severity and recommendation explanations.
6. Deepen cooking analytics.
7. Only then expand payments/orders/provider integrations.

## Executive Assessment

The project has moved beyond prototype infrastructure. The backend already has a broad FastAPI platform, auth, Redis queues, saga orchestration, agent/session infrastructure, NeoEats inventory/order/vision/cooking surfaces, and a public mobile-first frontend. The best near-term product path is to treat NeoEats as the flagship user experience and let the agent platform remain the hidden intelligence layer behind it.

The biggest opportunity is clear: NeoEats can become a practical grocery-to-cooking assistant if it reliably turns receipts, live scan, pantry state, user memory, and step-by-step cooking into one feedback loop. The biggest risk is also clear: the codebase is broad enough that development can fragment across too many product tracks before the core NeoEats loop is dependable.

Recommendation: focus the next phase on a public-quality NeoEats beta, not on expanding every platform surface at once.

## What Is Now Real

Recent verified state:

- Public `https://neoeats.no/` serves frontend HTML instead of backend JSON.
- Public and local registration work without invite or email confirmation.
- Local Vite development proxies `/api/*` and `/v1/*` to `127.0.0.1:8001`, avoiding browser CORS `Network Error`.
- Cloudflare Tunnel is split cleanly:
  - `neoeats.no` and `www.neoeats.no` -> Caddy/frontend on `localhost:8080`.
  - `api.neoeats.no` -> API on `127.0.0.1:8001`.
- Dashboard now uses authenticated `GET /api/v1/neoeats/dashboard`.
- Profile now uses authenticated `GET/PATCH /api/v1/neoeats/profile`, including editable dietary/allergy/avoidance/goal/cuisine fields.
- Live scan now returns stable `detection_id`, `icon_key`, category, confidence, and normalized bbox/center geometry.
- Frontend live scan markers are clamped into the visible camera container, including object-cover mobile crops.
- Confirmed scan/pantry/chat/profile dietary/recipe feedback/cooking signals are recorded as append-only `neoeats_user_memory_events`.
- Authenticated `GET /api/v1/neoeats/memory` exposes structured memory, controls, embedding coverage and user-scoped RAG event retrieval.
- `src/context/UserContext.tsx` mock profile was removed from the active frontend.
- Profile payment cards are no longer fake; payment methods remain empty until a real provider is connected.
- Receipt fallback no longer invents fake `milk` or `bread` items when provider extraction fails.
- Public API was rebuilt and verified after the new NeoEats profile/dashboard router was added.

## Verification Snapshot

Verified on 2026-05-06:

- Backend targeted tests:
  - `python -m pytest -q tests/unit/test_neoeats_rag_memory.py tests/unit/test_neoeats_vision_geometry.py tests/unit/test_neoeats_profile_routes.py tests/unit/test_auth_open_registration.py tests/unit/test_receipt_fallback_no_fake_items.py`
  - Result: `20 passed`.
- Frontend unit tests:
  - `npm run test:unit`
  - Result: `9 passed`.
- Frontend production build:
  - `npm run build`
  - Result: passed; Vite still warns about a large main chunk and mixed Capacitor camera imports.
- NeoEats smoke flow:
  - `npm run smoke:flow`
  - Result: passed.
- Public API checks:
  - `https://neoeats.no/` returns frontend HTML.
  - `https://neoeats.no/api/v1/auth/register` returns `200`.
  - `POST /api/v1/vision/analyze` returns stable `detection_id`, `icon_key`, category, confidence, and geometry through public routing.
  - `POST /api/v1/vision/analyze` with `confirm=true` records scan confirmations into `neoeats_user_memory_events`.
  - `GET /api/v1/neoeats/memory?query=milk+tomato+recipe` returns user-scoped RAG events.
  - `POST /api/v1/actions/invoke` chat receives `user_rag_memory_context` from prior scan confirmations.
  - Authenticated `GET /api/v1/neoeats/profile` returns the registered user profile.
  - Authenticated `GET /api/v1/neoeats/dashboard` returns real aggregate shape with source flags.
- Mobile smoke check:
  - `390x844` viewport.
  - Dashboard and Profile load after registration.
  - No horizontal overflow.
  - Profile shows no mock payment methods.

## Product Prospects

### NeoEats

Prospect: high, if development stays focused.

Why:

- The user loop is tangible: scan food, build pantry, get recommendations, cook, learn preferences.
- Mobile-first UX makes sense for grocery and kitchen contexts.
- The backend already has enough domain primitives to support a real beta.
- Public routing and open registration now remove the biggest access blockers.

Risks:

- Live scan reliability is still the most visible trust breaker.
- Product/catalog data is not yet a real commercial-grade source of truth.
- Nutrition/pricing/recommendation quality still contains heuristic fallbacks.
- The frontend bundle is heavy for mobile users.

Verdict: NeoEats should be the primary product track for the next phase.

### Agent Platform

Prospect: high as infrastructure, medium as standalone product right now.

Why:

- Agent sessions, tool permissions, sandboxing, budgets and saga execution create a strong platform base.
- This layer can differentiate NeoEats by making the assistant more useful than a static recipe app.

Risks:

- Selling or expanding the platform before the flagship product is reliable will dilute effort.
- Operational safety, observability and worker/sandbox health still need hardening.

Verdict: keep building it, but route the work through NeoEats use cases first.

### Learning, Career, Marketplace And Other Domains

Prospect: medium later, low priority now.

These domains demonstrate platform breadth, but they compete for attention. They should be paused as primary product tracks until NeoEats has a dependable public loop and the shared agent/runtime layer is operationally boring.

## Current Stub And Real-Data Gaps

Highest impact gaps:

- Live scan has a trusted first contract pass, but still needs camera-device QA across lighting, rotation, duplicate products, low-confidence products and native mobile capture fallback.
- Payment provider is not connected; Profile correctly shows empty payment state.
- Product catalog lacks real SKU/barcode/brand/price/availability ingestion.
- Nutrition and pricing are still heuristic when catalog data is missing.
- User memory now has append-only, searchable RAG events, profile controls, export/clear endpoints, recipe feedback learning, explicit dietary profile events, provider-backed embedding attempts and hybrid vector/lexical retrieval. Public runtime still falls back to lexical retrieval until an embedding provider/key is configured.
- Receipt extraction should gain provider telemetry, OCR confidence, validation errors and confirm-before-persist workflow.
- Orders need provider adapters/webhooks before payment/courier status can be called real production data.
- Frontend smoke server remains mock-only by design.
- LocalStorage order/cache fallback is useful offline behavior, but server state must remain authoritative.

## Strategic Direction

Use this product thesis:

NeoEats is a personal grocery and cooking agent that learns from the user's real pantry, receipts, scans, cooking behavior and preferences, then helps them waste less food and cook better meals.

This implies three engineering principles:

1. No invented food data.
2. Every user action should create useful future context.
3. Mobile reliability beats feature breadth.

## Recommended Development Order

### Sprint 1 - Live Scan Trust

Goal: make live scan feel dependable on mobile.

Status on 2026-05-06: first trustworthy contract pass is implemented and publicly verified. The remaining work is device QA and visual collision polish, not basic contract plumbing.

Work:

- Define a strict `vision_detection_v1` response contract.
- Normalize bbox, center, confidence, icon identity and stable detection IDs server-side.
- Add frontend overlay tests for marker-only detections, bbox detections, duplicate products and low-confidence states.
- Persist confirmed scan items through the pantry endpoint.
- Add mobile smoke scenarios for camera fallback and icon visibility.

Definition of done:

- Detected products always produce visible, non-overlapping icons when the backend returns names.
- User-confirmed detections become pantry items.
- Provider failure returns an empty/validation state, not fake products.

### Sprint 2 - User Memory And RAG

Goal: make the agent learn from the user in a controlled, inspectable way.

Status on 2026-05-25: append-only event memory is live for chat, confirmed scan/pantry additions, receipt confirmations, profile dietary edits, recipe feedback and cooking completion. Chat retrieval receives user-scoped RAG events, profile memory controls are available, embeddings/vector retrieval are wired when a provider is configured, and admin/global backfill endpoints plus `scripts/backfill_neoeats_memory_embeddings.py` are available. Next step is schedule wiring, provider monitoring, source labels, allergy severity and explanations.

Work:

- Keep `neoeats_user_memory_events` as the append-only memory table for chat facts, pantry changes, scan confirmations, receipt confirmations, profile dietary edits, recipe accepts/rejects and cooking completions.
- Wire the admin embedding backfill script into a real schedule and alert on provider unavailable/error states.
- Keep retrieval service blending recent, high-confidence, semantically relevant and lexically relevant memory.
- Expand profile controls into readable learned-fact inspection, source labeling, consent and allergy severity.
- Add tests proving memory from chat/pantry/cooking affects recommendations without leaking between users.

Definition of done:

- The agent can explain which user signals shaped a recommendation.
- Memory can be disabled or cleared per user.
- RAG retrieval is user-scoped and covered by tests.

### Sprint 3 - Product Catalog And Receipts

Goal: replace heuristic food facts with real product data.

Work:

- Add product catalog ingestion path for GTIN/barcode, brand, normalized name, category, unit, nutrition and allergens.
- Link `storage_item` to catalog products where possible.
- Add receipt provider telemetry: provider, model, confidence, raw OCR text, validation errors and retry state.
- Keep receipt persistence behind user confirmation.

Definition of done:

- Pantry items can point to stable product IDs.
- Receipt validation failures are actionable.
- Nutrition/pricing claims are marked as catalog-backed or estimated.

### Sprint 4 - Cooking Feedback Loop

Goal: make step-by-step cooking generate useful data.

Work:

- Persist cooking sessions and per-step progress.
- Record skipped steps, timer usage, ingredient consumption, leftovers and completion feedback.
- Feed cooking outcomes into user memory and recipe ranking.
- Add mobile QA for cooking mode on narrow screens.

Definition of done:

- Completing a cooking session updates pantry and memory.
- Future recommendations react to completion and rejection behavior.

### Parallel Platform Work

Keep this scoped and supportive:

- Fix CI dependency bootstrap.
- Reduce the NeoEats initial JS chunk by code-splitting camera, vision and cooking flows.
- Add worker/sandbox heartbeat health checks.
- Narrow broad router exception handling.
- Keep docs current as product gates change.

## 30-Day Roadmap

Week 1:

- Finish real-device live scan QA and trust tuning.
- Add tests around device-like camera fallback, detection geometry and frontend overlay rendering.
- Remove or archive legacy unused mock frontend services.

Week 2:

- Wire the admin embedding backfill script into a real schedule and add provider health monitoring.
- Add memory source labels, allergy severity and recommendation explanation cards.
- Keep expanding memory event coverage into substitutions and cooking outcomes.

Week 3:

- Build first catalog ingestion path.
- Add receipt telemetry and confirm-before-persist refinement.
- Add catalog-backed flags for nutrition/pricing.

Week 4:

- Persist cooking sessions.
- Split mobile bundle.
- Run public beta QA checklist across registration, scan, pantry, recommendation, cooking and profile.

## KPIs To Track

Product:

- Registration success rate.
- First pantry item added rate.
- Live scan confirmation rate.
- Receipt validation success rate.
- Recommendation acceptance rate.
- Cooking session completion rate.
- Repeat usage within 7 days.

Quality:

- API p95 latency for Dashboard/Profile/vision.
- Vision provider failure rate.
- Percentage of recommendations using catalog-backed data.
- Frontend initial JS size.
- Mobile horizontal overflow incidents.
- User-scoped RAG test coverage.

## Bottom Line

The project has a real chance if it narrows its focus. The strongest move is to make NeoEats excellent first: reliable mobile scan, real pantry data, inspectable user memory, catalog-backed food facts and a cooking loop that learns. The agent platform then becomes a strategic advantage inside a product people can actually use, instead of a powerful system looking for a flagship experience.
