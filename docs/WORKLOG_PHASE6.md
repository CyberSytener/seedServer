# Phase 6 Worklog — Evidence-Based Tasks

**Branch:** `chore/phase6-tasks`  
**Baseline:** 656 passed, 22 skipped, 1 deselected (95.82 s)  
**Deselected:** `tests/test_rate_limiter.py::TestRateLimiter::test_cleanup_old_windows` (timing-sensitive)  
**Started:** 2026-02-28

## Summary

| Task | Pri | Status | New Tests | Key Change |
|------|-----|--------|-----------|------------|
| T-4 | P1 | DONE | 0 (infra) | Dockerfile `python:3.11-slim` → `python:3.12-slim` |
| T-1 | P1 | DONE | 3 | Removed 19 broad `except Exception` from router_registration.py |
| T-2 | P1 | DONE | 5 | Registered OpenAI + Stub providers in UnifiedLLMService |
| T-6 | P2 | DONE | 0 (docs) | Documented worker_main.py; not used in docker-compose/CI |
| T-5 | P2 | DONE | 0 (comments) | LIFO middleware order docstring + comments |
| T-3 | P2 | DONE | 9 | `GenerationResult` dataclass + `*_with_metadata()` methods |

**Baseline:** 656 passed, 22 skipped, 1 deselected  
**Final:**   673 passed, 22 skipped, 1 deselected (+17 new tests, 0 regressions)

---

## T-4 (P1) — Dockerfile python:3.11-slim → 3.12-slim

**Status:** DONE  
**Evidence:** Dockerfile line 1 = `FROM python:3.11-slim`; `.github/workflows/*.yml` use `python-version: "3.12"`  
**Change:** `FROM python:3.11-slim` → `FROM python:3.12-slim`  
**Verification:** `Select-String` confirms line 1 = `FROM python:3.12-slim`  

---

## T-1 (P1) — Narrow broad Exception catches in router_registration.py

**Status:** DONE  
**Evidence:** 19 `except Exception as e` blocks at lines 35,45,54,63,73,83,94,105,118,128,138,148,158,169,179,189,200,210,219  
**Policy:** Remove broad `except Exception`; only suppress `ImportError`/`ModuleNotFoundError`; unexpected errors must propagate  
**Changes:** Removed all 19 `except Exception` blocks via regex script. Added policy docstring. Created `tests/unit/test_router_registration_policy.py` (3 AST-based tests).  
**Verification:** `python -m pytest tests/unit/test_router_registration_policy.py -v` → 3 passed  

---

## T-2 (P1) — Register OpenAI + Stub providers in UnifiedLLMService

**Status:** DONE  
**Evidence:** Only `GeminiClientAdapter` registered in `app/main.py` (~line 225). `OpenAIProvider` and `StubProvider` from `app/core/llm/router.py` conform to `LLMProvider` protocol.  
**Changes:** Added imports for `OpenAIProvider`+`StubProvider` from `app.core.llm.router`. Added registrations after Gemini block: OpenAI (guarded, uses `settings.openai_api_key`), Stub (unconditional). Created `tests/unit/test_unified_llm_registration.py` (5 tests).  
**Verification:** `python -m pytest tests/unit/test_unified_llm_registration.py -v` → 5 passed  

---

## T-6 (P2) — Verify worker_main.py entrypoint

**Status:** DONE  
**Evidence:** `app/worker_main.py` (123 lines) — Photo editing async job processor. Needs docker-compose/CI usage verified.  
**Findings:**  
- Purpose: `WorkerService` → `PhotoEditingWorker.process_jobs()` (async Redis queue consumer for photo edits)  
- Dependencies: Redis, Postgres (asyncpg), `OpenAIImageEditAdapter`, `PhotoBillingService`, `PhotoStorageService`  
- `docker-compose.yml` worker services (`worker_fast`, `worker_batch`, `worker_low`) use `scripts/run_worker.py` — **not** `worker_main.py`  
- No CI workflows reference `worker_main.py`  
- Run manually: `python -m app.worker_main`  
**Changes:** Updated `docs/ARCHITECTURE_MAP_POST_PHASE_5.md` §3 row 14 with verified description.  

---

## T-5 (P2) — Add middleware order comments

**Status:** DONE  
**Evidence:** `app/infrastructure/middleware_setup.py` (83 lines) — 3 decorators + 1 add_middleware, no order comments.  
**Changes:**  
- Added detailed docstring to `register_middleware()` with full LIFO execution order diagram  
- Updated `RequestIDMiddleware` comment to reference LIFO model  
- Added comment at registration call in `app/main.py` referencing CORS order and docstring  
**Verification:** Both files pass `ast.parse()`.  

---

## T-3 (P2) — Structured metadata methods on UnifiedLLMService

**Status:** DONE  
**Evidence:** `generate()`/`agenerate()` in `app/core/llm/unified.py` return `str`. Saga orchestrator needs token counts, provider info.  
**Changes:**  
- Added `GenerationResult` frozen dataclass to `app/core/llm/protocol.py` (fields: text, provider, model, tokens_in, tokens_out, cost_usd, extra)  
- Added `generate_with_metadata()` and `agenerate_with_metadata()` to `UnifiedLLMService`  
- Existing `generate()`/`agenerate()` unchanged (backward compat)  
- Created `tests/unit/test_generation_result.py` (9 tests: dataclass, frozen, full construction, both wrappers, backward compat)  
**Verification:** `python -m pytest tests/unit/test_generation_result.py -v` → 9 passed  

---
