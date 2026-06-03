# State Mark - 2026-05-19

This document marks the current project state after the system review, public runtime recovery, receipt confirmation wiring, cleanup inventory pass on 2026-05-19, the NeoEats live-scan/product-icon/trust-contract stabilization passes on 2026-05-23, the profile dietary/RAG pass on 2026-05-25, the early-launch activation-loop pass on 2026-05-26, the public Redis/tunnel correction on 2026-05-28, the mobile Add Food trust pass on 2026-05-28, and the live scan fallback pass on 2026-05-29.

## Scope

Active roots:

- Backend and platform: `C:\Users\Exempel\Desktop\seed.server.v5\seed_server`
- NeoEats frontend snapshot: `C:\Users\Exempel\Desktop\seed.server.v5\front-neoeats-snapshot`

Archive/snapshot roots are outside active development:

- `C:\Users\Exempel\Desktop\seed.server.v5\_archive`
- `C:\Users\Exempel\Desktop\seed.server.v5\*.zip`

## Current Runtime State

Public runtime was initially down with Cloudflare `530`. It was restored by starting Docker Desktop, starting the `seed_public` compose services and starting `cloudflared`. On 2026-05-28, a stale manual `python -m uvicorn app.main:app --port 8001` process was also removed because it intercepted public API traffic and made health report `redis=false` while the compose API was healthy internally.

Verified after recovery:

- `https://neoeats.no/` returns frontend HTML.
- `https://www.neoeats.no/` returns frontend HTML.
- `https://api.neoeats.no/health` returns healthy backend JSON with `redis=true`.
- `seed_public` compose services are running: `postgres`, `redis`, `api`, `scheduler`, `worker_fast`, `worker_batch`, `worker_low`.
- `cloudflared` is running with `C:\Users\Exempel\.cloudflared\config.yml`.
- `scripts/restore_public_runtime.ps1` now validates `redis=true`, validates frontend HTML, and can stop a stale manual `uvicorn app.main:app` listener before recreating the compose API.

Important ports:

- Caddy/frontend: `localhost:8080`
- Public API bind: `127.0.0.1:8001`
- Local Vite frontend: `127.0.0.1:5173`
- Frontend smoke server: `127.0.0.1:5174`

## Current Functional State

NeoEats:

- Open beta registration works without invite or email confirmation.
- Dashboard/Profile use authenticated backend endpoints.
- Inventory ledger is server-backed.
- Live scan returns stable detection fields and frontend overlay markers are clamped into visible camera bounds.
- Product icon rendering is no longer mojibake-prone: the frontend resolver uses backend `icon_key`, product-name matching and saved `metadata.icon_key`; backend vision now emits more specific keys for cheese, poultry, potato and onion.
- Live scan now dedupes overlapping same-product detections server-side and returns `dedupe_key`, `trust_level`, `review_required` and `duplicate_count` when applicable. The frontend surfaces `Good`/`Check`/`Review` labels and stores the trust metadata with saved pantry rows.
- Receipt review in the frontend now posts to `/api/v1/vision/receipt/confirm`.
- Receipt confirmation writes receipt history, pantry storage, inventory item price updates, ledger events and `receipt_item_confirmed` RAG memory.
- RAG memory is append-only and user-scoped, with explicit `neoeats_memory_controls` in profile metadata. Users can disable learning, disable RAG retrieval, disable individual sources, export memory, or clear structured and event memory. Retrieval now supports hybrid vector plus lexical ranking: memory writes store pgvector embeddings when an embedding provider is available, chat/profile retrieval uses vector similarity plus token/confidence/type/subject/recency scoring, and lexical retrieval remains the safe fallback. Memory stats expose embedding status/coverage, `/api/v1/neoeats/memory/embeddings/backfill` can backfill current-user pending/failed/unavailable events, and admin-protected `/api/v1/neoeats/memory/embeddings/admin/status` plus `/api/v1/neoeats/memory/embeddings/admin/backfill` now expose global backlog stats and all-user backfill for scheduled/operator runs. Recipe recommendation actions now write `recipe_feedback_accepted` / `recipe_feedback_rejected` memory events through `/api/v1/neoeats/recipes/feedback`, gated by the dedicated `recipe` memory source; recipe cards also collect rating/reason chips so RAG can distinguish price, effort, inventory-gap and taste-mismatch feedback. Profile now has editable dietary/allergy/avoidance/goal/cuisine fields, stored in `users.meta_json.neoeats_profile.dietary_profile`, exposed through `/profile`, gated by the `profile` memory source, and recorded as `profile_dietary_updated` RAG events.
- Cooking completion updates pantry and records memory.
- Early-launch activation telemetry now records the first user loop under `users.meta_json.neoeats_launch_events`: registration, server-normalized first food added, food added, live scan save, receipt confirmation, recommendation request/success/failure, missing-list save/confirm, recommendation feedback, recipe save, cooking start/completion and food-rule edits. User-scoped `GET/POST /api/v1/neoeats/launch/events` and admin `GET /api/v1/neoeats/launch/events/admin/summary` expose event counts, first/last seen timestamps and activated-user counts.
- NeoEats Home now prioritizes the early-launch path with `Add food`, `Rules` and `Ask chef`; the empty pantry CTA is `Add Food`, and the previously hardcoded Orders notification dot is disabled.
- The mobile Add Food flow is now user-level instead of demo-like: the Fridge page is titled `Add Food`, exposes `Live scan`, `Type items`, and `Search foods` as first actions, and Quick Add is portal-rendered so bottom navigation cannot intercept save clicks. Search saves close back to the pantry view, and text-entry modes no longer show nonfunctional voice controls.
- Dashboard/pantry freshness now avoids false `0%` readings for saved, non-expired items when the backend does not send a positive freshness value. Product icons for common first-run staples such as Butter, Olive Oil and Garlic are resolved through the frontend product-icon resolver.
- Live scan now has a visible no-camera/permission fallback inside the fullscreen scanner: `Live scan paused`, `Camera not available`, retry, and `Back to Photo Upload`. This keeps the early-user path recoverable on desktops, simulators and phones where camera permission or device access fails.
- Commerce CTAs in early-launch NeoEats UI are gated by `VITE_NEOEATS_COMMERCE_ENABLED=true`. By default Explore, Fridge hybrid recipes and recipe-brain missing-item flows save missing ingredient drafts through `GET/POST/DELETE /api/v1/neoeats/missing-lists`, backed by `users.meta_json.neoeats_missing_lists` with frontend local cache fallback, instead of presenting unbacked order/buy promises; generic commerce cards render as `Preview Only`. Missing-list drafts are enriched from store catalog rows (`inventory_item` plus `inventory_lot`) when available: matched items receive `catalog_item_id`, `sku`, category, catalog unit, last paid price, stock availability and match confidence. Explore now includes a `Saved Missing Lists` review panel with matched/stock/price details plus confirm/remove actions; confirming a list writes `missing_list_confirmed` telemetry without starting checkout.

Known limitations:

- Product catalog is not yet a complete GTIN/barcode/nutrition/allergen source of truth.
- Missing-list drafts are server-backed, user-scoped and store-catalog-enriched, but still need GTIN/barcode normalization, stock/price refresh policy, receipt-line linking and a proper order/checkout transition before becoming commerce.
- Receipt provider telemetry and retry/refine UI are incomplete.
- Live scan still needs real-device QA for lighting, rotation, same-product multi-instance tuning and native camera fallback.
- RAG retrieval is controlled and explainable, but still needs production telemetry dashboards/alerts around embedding provider errors, actual scheduler wiring for the admin backfill script, allergy severity/consent UX and retention policy before calling it mature personalization.
- Launch telemetry is stored as compact per-user JSON for early beta learning; if user volume grows, move it into an append-only analytics table or event stream before relying on it for long-term cohort analytics.
- Payments/orders are not production-provider-backed and should remain gated/lower priority until catalog, receipt confirmation and user memory are more trusted.
- Frontend bundle is still large for mobile.
- Live scan is clearer at the UI shell level, but still needs real-device camera QA for lighting, rotation, permission prompts and actual detection confidence before it can be treated as trusted production input.

## Current Verification

Backend:

```powershell
python -m pytest -q tests\unit\test_neoeats_rag_memory.py tests\unit\test_receipt_fallback_no_fake_items.py tests\unit\test_receipt_confirm_routes.py
```

Expected current result: targeted receipt/memory tests pass.

Verified result after adding receipt confirmation route coverage:

- `9 passed` for `test_receipt_confirm_routes.py`, `test_neoeats_rag_memory.py`, and `test_receipt_fallback_no_fake_items.py`.

Verified result after the 2026-05-23 live icon/trust pass:

- `42 passed` for `test_neoeats_vision_geometry.py`, `test_neoeats_inventory_extract.py`, and `test_product_normalize.py`.
- `49 passed` for the standard backend gate: CI smoke, auth context, security hardening, OpenAI router regression, open registration, NeoEats RAG memory, receipt confirmation, diagnostics serialization, lesson cost accounting and vision geometry.
- `58 passed` for the expanded backend gate after adding NeoEats memory controls/export/clear and profile route coverage.
- `60 passed` for the expanded backend gate after adding provider-backed NeoEats memory embeddings and hybrid vector/lexical retrieval coverage.
- `65 passed` for the expanded backend gate after adding embedding coverage telemetry and current-user backfill coverage.
- `68 passed` for the expanded backend gate after adding recipe feedback memory events and the `recipe` memory source.
- `68 passed` again after adding recipe feedback rating/reason chip payloads.
- `70 passed` for the expanded backend gate after adding editable dietary profile storage, profile-source memory gating and `profile_dietary_updated` RAG events.
- `76 passed` for the expanded backend gate after adding admin/global embedding backlog stats, all-user embedding backfill, dry-run coverage and the scheduler-friendly backfill script.
- `18 passed` for `tests\unit\test_neoeats_profile_routes.py` after adding launch telemetry endpoints and admin summary coverage.
- `59 passed` for the NeoEats/auth/receipt/cooking/RAG subset after the early-launch activation pass.
- `20 passed` for `tests\unit\test_neoeats_profile_routes.py` after adding server-side first-food normalization and recommendation outcome telemetry.
- `72 passed` for the NeoEats/auth/receipt/cooking/RAG subset after the recommendation outcome and beta commerce-gate pass.
- `23 passed` for `tests\unit\test_neoeats_profile_routes.py` after adding missing-list draft APIs and launch telemetry.
- `75 passed` for the NeoEats/auth/receipt/cooking/RAG subset after adding missing-list drafts.
- `24 passed` for `tests\unit\test_neoeats_profile_routes.py` after enriching missing-list drafts from store catalog rows.
- `76 passed` for the NeoEats/auth/receipt/cooking/RAG subset after adding catalog enrichment.
- `25 passed` for `tests\unit\test_neoeats_profile_routes.py` after adding missing-list confirmation.
- `77 passed` for the NeoEats/auth/receipt/cooking/RAG subset after adding the Explore missing-list review/confirmation flow.

Frontend:

```powershell
npm run test:unit
npm run build
```

Expected current result:

- Unit tests pass.
- Build passes with known chunk warnings.

Verified result:

- `npm run test:unit` passed with `9 passed`.
- `npm run build` passed earlier in this stabilization pass with the known large chunk warning.
- `npm run test:unit -- --run src/utils/emoji.test.ts src/utils/visionOverlay.test.ts` passed with `9 passed`.
- `npm run build` passed after the icon resolver update with the known large chunk warning.
- `npm run build` passed again after the live scan trust metadata update with the same known large chunk warning.
- `npm run build` passed after adding the profile AI Memory control panel, with the same known large chunk warning.
- `npm run test:unit -- --run src/utils/emoji.test.ts src/utils/visionOverlay.test.ts` still passed with `9 passed`, and `npm run build` passed after adding recipe feedback chips, with the same known large chunk warning.
- `npm run test:unit -- --run src/utils/emoji.test.ts src/utils/visionOverlay.test.ts` still passed with `9 passed`, and `npm run build` passed after adding Dietary Profile UI and removing demo chat taste/context fallbacks, with the same known large chunk and Capacitor camera warnings.
- `npm run test:unit` passed with `14 passed`, and `npm run build` passed after adding early-launch telemetry hooks and the first-loop Home CTA. `npm test -- --run` is not a valid script in this frontend package.
- `npm run test:unit` passed with `14 passed`, and `npm run build` passed after adding recommendation outcome telemetry and the beta commerce-gate helper. Build still has the known large chunk and Capacitor camera split warnings.
- `npm run test:unit` passed with `14 passed`, and `npm run build` passed after switching missing-list saves to server-backed drafts with local fallback. Build still has the known large chunk and Capacitor camera split warnings.
- `npm run test:unit` passed with `14 passed`, and `npm run build` passed after surfacing missing-list catalog match counts on saved drafts. Build still has the known large chunk and Capacitor camera split warnings.
- `npm run test:unit` passed with `14 passed`, and `npm run build` passed after adding the Explore missing-list review panel and confirm/remove hooks. Build still has the known large chunk and Capacitor camera split warnings.
- `npm run test:unit` passed with `14 passed`, and `npm run build` passed after the 2026-05-28 mobile Add Food trust pass. Local mobile browser QA at `390x844` verified Dashboard freshness `100%`, visible Garlic/Olive Oil/Butter product icons, the Add Food hub, Quick Add/Search save without bottom-nav interception, Chat copy without internal debug labels, and Live Scan camera-required state with `Live scan ready`.
- `npm run test:unit` passed with `16 passed`, and `npm run build` passed after the 2026-05-29 live scan fallback pass. Local mobile browser QA at `390x844` verified the no-camera live scan state and `Back to Photo Upload` recovery. Browser screenshot capture timed out in the in-app browser CDP path, so verification used DOM state.
- Local browser check on `http://127.0.0.1:5173/` created test user `launch_mplvzlrv`, verified the Home first-loop CTA labels, confirmed the Orders notification dot is not shown, confirmed `Add food` navigates to Smart Fridge, and found no browser console warnings/errors.
- Local browser check on `http://127.0.0.1:5173/` after the commerce-gate pass verified the app loaded with no console errors, Home showed `Preview Only` instead of unbacked add-to-cart copy, Explore loaded with `Preview Only` cards, and visible Explore text no longer showed `Quick Order` or `Order Missing Items` while commerce is disabled.

Public UI browser check after the 2026-05-23 icon pass:

- `https://neoeats.no/` loaded with no browser console errors.
- Public UI registration completed without network error.
- Quick Add/Search rendered real product icons for cheese, milk, eggs, bread, chicken and related items.
- After the live scan trust update, `https://neoeats.no/` still loaded as frontend HTML with no browser console errors, visible product icons remained correct and no mojibake markers were visible.
- Public `POST /api/v1/vision/analyze` returned the new trust contract: overlapping Cheese detections deduped to one item with `duplicate_count=2` and `trust_level=trusted`; Tomato returned as `trust_level=check`.
- After the NeoEats memory controls update, the public Profile UI showed the `AI Memory` panel with `Learning`, `RAG recall`, `Personalization`, source toggles and `Clear`, with no browser console errors.
- Visible page text did not contain `рџ` mojibake markers.

Public smoke:

```powershell
.\scripts\smoke_public_neoeats.ps1
```

Expected current result:

- frontend HTML OK
- API health OK
- registration OK
- receipt confirmation OK
- receipt history OK
- receipt memory OK

Verified result:

- `.\scripts\smoke_public_neoeats.ps1` returned `ok=true`, `itemsSaved=1`, `memoryEvents=1`.
- `.\scripts\restore_public_runtime.ps1` returned public runtime healthy after rebuilding public API/worker containers; smoke user `smoke_615bb3f1d5`, receipt `865f84e2-5740-46bd-b92a-b0bff9658651`, `itemsSaved=1`, `memoryEvents=1`.
- After the memory controls rebuild, `.\scripts\restore_public_runtime.ps1` again returned public runtime healthy; smoke user `smoke_c5a0afd602`, receipt `06d5d5f7-ea01-4219-bca3-ae1e56091800`, `itemsSaved=1`, `memoryEvents=1`.
- Public memory smoke user `memory_a4939e9791`: `/profile` returned default controls, `/memory/settings` disabled RAG recall and chat learning, `/memory` respected disabled retrieval, `/memory/export` returned `neoeats_memory_export_v1`, and `DELETE /memory` returned `rag_events_cleared=true`.
- After the embedding coverage/backfill rebuild, public runtime was rebuilt with `docker compose -p seed_public -f docker-compose.public.yml --env-file .env.public up -d --build api scheduler worker_fast worker_batch worker_low`; `.\scripts\restore_public_runtime.ps1` returned smoke user `smoke_1c1782896e`, receipt `c644f29e-4798-4bdc-8cf9-9173dd8b8916`, `itemsSaved=1`, `memoryEvents=1`.
- Public hybrid memory smoke user `hybrid_2da8a03706`: `/memory` returned `memory_stats.by_embedding_status.unavailable=1`, `retrieval.mode=lexical_event_rag`, confirming safe fallback while no public embedding provider/key is active.
- Public backfill smoke user `backfill_b2d1970476`: `POST /memory/embeddings/backfill` returned `reason=embedding_provider_unavailable`, `attempted=0`, `skipped=5`; `/memory` returned `embedding_coverage_pct=0.0`, confirming the endpoint is explicit about missing provider state.
- After the recipe feedback memory rebuild, public runtime was rebuilt with `docker compose -p seed_public -f docker-compose.public.yml --env-file .env.public up -d --build api scheduler worker_fast worker_batch worker_low`; `.\scripts\restore_public_runtime.ps1` returned smoke user `smoke_7f86beb9eb`, receipt `360f89b7-825c-4b77-89ce-97c5445fa756`, `itemsSaved=1`, `memoryEvents=1`.
- Public recipe feedback smoke user `recipe_smoke_98799fd8d2`: `POST /api/v1/neoeats/recipes/feedback` recorded `recipe_feedback_accepted` event `5f494665-10cd-42b3-bb56-4ff21e96c32c`; `GET /api/v1/neoeats/memory?query=salmon%20bowl` retrieved one event with source `recipe_feedback`, score `0.7346`, `rag_events_ready=true`, and `rag_embedding_provider_available=false`.
- After the recipe feedback reason/rating rebuild, public runtime was rebuilt with `docker compose -p seed_public -f docker-compose.public.yml --env-file .env.public up -d --build api scheduler worker_fast worker_batch worker_low`; `https://neoeats.no/`, `https://www.neoeats.no/`, and `https://api.neoeats.no/health` returned `200`.
- Public recipe reason smoke user `recipe_reason_0fb7e1d08e`: `POST /api/v1/neoeats/recipes/feedback` recorded `recipe_feedback_rejected` event `a0374cf4-6868-48f3-a8e7-377414300a17`; `GET /api/v1/neoeats/memory?query=ratatouille%20missing%20ingredients` retrieved one event with source `recipe_feedback`, score `0.7235`, `rating=2`, `reason_code=missing_too_much`, `reason_tags=[inventory_gap, shopping_needed]`, `rag_events_ready=true`, and `rag_embedding_provider_available=false`.
- After the Dietary Profile rebuild, public runtime was rebuilt with `docker compose -p seed_public -f docker-compose.public.yml --env-file .env.public up -d --build api scheduler worker_fast worker_batch worker_low`; `.\scripts\restore_public_runtime.ps1` returned smoke user `smoke_83488cf999`, receipt `91a9f784-122d-4b3c-b61f-dbdb11cdd0d8`, `itemsSaved=1`, `memoryEvents=1`, while `cloudflared` was already running as PID `248`.
- Public dietary profile smoke user `dietary_smoke_2774fe4511`: `PATCH /api/v1/neoeats/profile` stored `vegetarian`, `peanut`, `cilantro`, `budget_friendly`, `quick_meals` and `japanese`; `GET /api/v1/neoeats/memory?query=peanut%20cilantro%20japanese%20budget` retrieved `profile_dietary_updated` event `83dfb002-d2cb-4a2a-bc10-550e715c16d4` from source `profile_preferences` with score `0.675`, and `rag_embedding_provider_available=false`.
- Latest restore check after rebuilding the frontend dist returned `https://neoeats.no/`, `https://www.neoeats.no/` and `https://api.neoeats.no/health` OK; `.\scripts\restore_public_runtime.ps1` returned smoke user `smoke_bcffa4ef53`, receipt `edaa2eb7-775e-4913-b3bf-db4d370a0822`, `itemsSaved=1`, `memoryEvents=1`, and `cloudflared` remained running as PID `248`.
- After adding admin/global embedding backfill, public API/worker images were rebuilt and recreated; `.\scripts\restore_public_runtime.ps1` returned smoke user `smoke_8ce0d7c0f3`, receipt `5f930fc7-a4ec-45ec-9ef5-ec842466f4f3`, `itemsSaved=1`, `memoryEvents=1`, with `cloudflared` still PID `248`.
- Public admin embedding dry-run via `scripts\backfill_neoeats_memory_embeddings.py --dry-run --max-users 3 --limit-per-user 1` returned `ok=true`, `backlog_event_count=41`, `backlog_user_count=31`, `embedding_coverage_pct=0.0`, `provider_available=false`, `reason=dry_run`, and selected three candidate users without writing embeddings.
- After the 2026-05-28 Redis/tunnel correction, `.\scripts\restore_public_runtime.ps1 -SkipDocker -SkipSmoke` returned healthy local API, Caddy, one running `cloudflared` process and public checks. `.\scripts\smoke_public_neoeats.ps1` returned `ok=true`, user `smoke_a827a7bf25`, receipt `e21123ff-9b7c-4777-a3a8-63b784dd5683`, `itemsSaved=1`, `memoryEvents=1`.
- After the 2026-05-29 live scan fallback build, public checks initially returned Cloudflare `1033`; `scripts\restore_public_runtime.ps1 -SkipSmoke` restarted Docker Desktop/`seed_public` and `cloudflared`. Public health then returned `ok=true`, `redis=true`, `db=true`, `https://neoeats.no/` returned frontend HTML with the current `dist` asset, and `.\scripts\smoke_public_neoeats.ps1` returned `ok=true`, user `smoke_58a314e1dd`, receipt `6d48bba6-cfae-4786-ad79-21255978205e`, `itemsSaved=1`, `memoryEvents=1`.
- `scripts\audit_deleted_references.ps1` returned `NO_REFERENCES_FOUND 189`.
- `python scripts\verify\verify_ci_security.py` returned `OK READY FOR CI VERIFICATION`.

## Repository State

The backend repository is still not release-clean.

Observed after the latest cleanup-audit pass on 2026-05-23:

- `3604` git status entries from `scripts/audit_worktree.ps1`
- `3151` tracked deletions
- `88` modified files
- `365` untracked files

Current cleanup bucket summary:

- `COMMIT_NOW`: `48` entries
- `NEOEATS_PUBLIC_BETA`: `12` entries
- `PLATFORM_APP_REVIEW`: `61` entries
- `INFRASTRUCTURE_REVIEW`: `25` entries
- `AGENT_PLATFORM_REVIEW`: `15` entries
- `REALTIME_PLATFORM_REVIEW`: `2` entries
- `ACTIVE_CODE_REVIEW`: `4` entries
- `TEST_REVIEW`: `108` entries
- `SCRIPT_REVIEW`: `84` entries
- `MIGRATION_REVIEW`: `11` entries
- `REPLACED_CLEANUP_READY`: `165` deleted entries
- `TEST_COVERAGE_REBUILD`: `24` deleted entries
- `DELETE_IN_CLEANUP_BRANCH`: `2667` entries
- `ARCHIVE_REVIEW`: `290` entries
- `MANUAL_REVIEW`: `88` entries

Focused import reference audit on 2026-05-20:

- `189` deleted code/config files checked
- `189` no active references found
- `0` remaining referenced candidates
- runtime imports fixed for deleted top-level modules: `app.ab_testing`, `app.alerting`, `app.diagnostic_engine`, `app.learning_path`, `app.learning_plan`, `app.slo_monitor`, `app.worker_redis`
- missing-target relative imports fixed in `app.core.ab_testing`, `app.services.diagnostic.engine`, `app.services.pipeline.pipeline.steps`, and `app.services.learning_plan`
- lesson pipeline repair now handles common LLM output drift (`word_order` skill aliases, nested `grading` answers, missing `lessonId`, schema-valid padding)
- old `app/realtime/*` layer has no active import references; active realtime code lives under `app/core/realtime/*` and `app/models/realtime/*`
- deleted old `.github`, `app/realtime/*`, `app/optimizer/*`, flat `app/*.py`, old `app/pipeline/*`, and old `app/monitoring/metrics.py` entries are now classified as `REPLACED_CLEANUP_READY`
- deleted legacy tests and old script tests are now classified as `TEST_COVERAGE_REBUILD`
- the broad `VERIFY_IMPORTS` bucket has been retired; remaining active entries are split by owner/risk in `docs/ACTIVE_REVIEW_BUCKETS_2026-05-20.md`
- NeoEats public-beta code is now separated from broader platform work as `NEOEATS_PUBLIC_BETA`.

This must be treated as a work management risk. Do not mix cleanup, docs, generated files and product changes into one final commit.

Safe cleanup performed in this pass:

- removed untracked `.tmp_any.jpg`
- removed untracked `.tmp_food.jpg`
- removed untracked `.tmp_neoeats_index.html`
- removed untracked `.vite/`
- removed old ignored `logs/bot/` simulation logs
- removed old ignored `logs/sim_output_v*.txt`
- ignored/classified local scratch extraction and benchmark outputs: `.tmp_openclaw_extract/`, `.seed_artifacts/`, `scripts/_*.py`, `scripts/bench_*.txt`, `scripts/*_results.txt`, `scripts/startup_trace.txt`, `scripts/detour_dist.txt`

Left intentionally:

- `logs/public/`, because current public tunnel recovery logs are useful until service automation is finished.

Reproducible cleanup audit:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\audit_worktree.ps1
```

Public runtime wrapper:

```powershell
.\scripts\restore_public_runtime.ps1
```

## Current Source Of Truth

Use these files as the live entrypoints:

- `README.md`
- `SOURCE_OF_TRUTH.md`
- `PROBLEMS_AND_TASKS.md`
- `docs/SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19.md`
- `docs/STATE_MARK_2026-05-19.md`
- `docs/PROJECT_CLASSIFICATION_2026-05-19.md`
- `docs/CLEANUP_INVENTORY_2026-05-19.md`
- `docs/VERIFY_IMPORTS_AUDIT_2026-05-20.md`
- `docs/ACTIVE_REVIEW_BUCKETS_2026-05-20.md`
- `docs/PUBLIC_RUNTIME_RUNBOOK_2026-05-19.md`
- `docs/guides/DOCUMENTATION_INDEX.md`

Older phase reports are historical unless explicitly re-verified.

## Next Cleanup Gate

Before broad new feature development:

1. Categorize all dirty files.
2. Move generated/runtime files to ignore or archive.
3. Split documentation, product code, cleanup and CI fixes into separate commits or branches.
4. Keep `scripts/audit_worktree.ps1` and `docs/CLEANUP_INVENTORY_2026-05-19.md` current while reducing status noise.
5. Start product catalog ingestion work only after the above is explainable.
