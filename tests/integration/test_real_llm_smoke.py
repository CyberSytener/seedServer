from __future__ import annotations

import os

import pytest

from app.infrastructure.monitoring.monitoring.metrics import BillingMetrics
from app.settings import get_settings
from app.services.llm import build_credit_ledger_event, normalize_usage_breakdown
from app.sim.llm_stub import RealLLMPipelineAdapter


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.real_smoke
@pytest.mark.asyncio
async def test_real_llm_smoke_for_cheap_gemini_model() -> None:
    if str(os.getenv("SEED_TEST_ALLOW_REAL_LLM", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip("set SEED_TEST_ALLOW_REAL_LLM=1 to run real-provider smoke tests")

    settings = get_settings()
    if not settings.gemini_api_key:
        pytest.skip("real Gemini smoke test requires GEMINI_API_KEY")

    model = (
        os.getenv("SEED_GEMINI_MODEL_CHEAP")
        or os.getenv("SEED_GEMINI_MODEL_FAST")
        or settings.gemini_model_fast
        or "gemini-2.0-flash-lite"
    )
    adapter = RealLLMPipelineAdapter(provider="gemini", model=model, timeout_sec=45, max_attempts=2)
    result = await adapter.run_step(
        {
            "step": "smoke",
            "task_type": "general",
            "mode": "fast",
            "inputs": {
                "prompt": (
                    "User request simulation: propose one 15-minute English speaking drill "
                    "for A2 level. Return one concise sentence."
                )
            },
        }
    )

    output = result.get("output") if isinstance(result, dict) else {}
    answer = str((output or {}).get("answer") or "").strip()
    assert answer, f"gemini/{model} returned empty output"

    usage = normalize_usage_breakdown(result.get("usage") if isinstance(result, dict) else None)
    assert usage.total_tokens > 0

    event = build_credit_ledger_event(
        provider="gemini",
        model=model,
        endpoint="/sim/smoke",
        feature="real_llm_smoke",
        stage="smoke",
        usage=usage,
        attempt=1,
    )
    event_payload = event.to_dict()
    BillingMetrics.record_credit_ledger_event(event_payload)

    assert event_payload["provider"] == "gemini"
    assert event_payload["model"] == model
    assert event_payload["usage"]["total_tokens"] > 0
    assert event_payload["credits_charged"] >= 0
