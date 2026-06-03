# Minimal Test Suite

This project keeps a lean test suite focused on core service behavior.

## Included

- API/Auth: tests/test_api.py, tests/test_auth_flows.py, tests/test_auth_verify_user_context.py
- Core sanity: tests/test_ci_smoke.py, tests/test_rate_limiter.py, tests/test_validators.py
- Realtime (saga + websocket): tests/unit/realtime/test_action_router.py, tests/unit/realtime/test_action_router_saga_integration.py, tests/unit/realtime/test_saga_orchestrator.py, tests/unit/realtime/test_saga_orchestrator_async_reserve.py, tests/unit/realtime/test_saga_orchestrator_db_error.py, tests/unit/realtime/test_websocket_auth.py, tests/unit/realtime/test_websocket_gateway.py, tests/unit/realtime/test_websocket_session.py, tests/unit/realtime/test_contracts.py
- Integration (core flows): tests/integration/test_career_growth_saga_e2e.py, tests/integration/test_cv_flow.py, tests/integration/test_ws_action_flow.py, tests/integration/test_ws_cv_flow.py
- Unit (LLM contracts): tests/unit/test_llm_validator.py, tests/unit/test_prompt_system.py

## Notes

- Live-server integration tests were removed to avoid false negatives when the API is not running locally.
- Deleted tracked legacy tests are mapped in docs/TEST_COVERAGE_CLEANUP_2026-05-20.md.
- If you need to reintroduce any removed tests, port them to current module paths first.

## Real Gemini Smoke

Run secrets-gated cheap-model smoke checks (Gemini only):

```bash
SEED_TEST_ALLOW_REAL_LLM=1 \
SEED_GEMINI_MODEL_CHEAP=gemini-2.0-flash-lite \
pytest -W "ignore::PendingDeprecationWarning" -q \
  tests/integration/test_real_llm_smoke.py \
  tests/integration/test_real_simulation_gemini_smoke.py
```

Run the simulation harness directly in real mode with explicit cheap Gemini model:

```bash
SEED_TEST_ALLOW_REAL_LLM=1 \
SIM_LLM_MODE=real \
SIM_LLM_PROVIDER=gemini \
SIM_LLM_MODEL=gemini-2.0-flash-lite \
python -m app.sim.run --llm-mode real --llm-provider gemini --llm-model gemini-2.0-flash-lite
```
