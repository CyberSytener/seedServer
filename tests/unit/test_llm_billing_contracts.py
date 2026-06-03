from __future__ import annotations

import json

from app.services.llm.contracts import (
    build_credit_ledger_event,
    normalize_usage_breakdown,
)


def test_build_credit_ledger_event_is_json_safe_and_totals_are_correct():
    mocked_provider_usage = {
        "prompt_tokens": 120,
        "completion_tokens": 80,
        "total_tokens": 200,
        "cached_tokens": 10,
    }

    usage = normalize_usage_breakdown(mocked_provider_usage, request_count=1)
    event = build_credit_ledger_event(
        provider="gemini",
        model="gemini-2.0-flash",
        endpoint="/v1/lessons/generate",
        feature="lesson_generation",
        stage="candidate",
        usage=usage,
        attempt=1,
        trace_id="trace_1",
        session_id="session_1",
        job_id="job_1",
    )

    payload = event.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False)

    assert encoded
    assert payload["usage"]["prompt_tokens"] == 120
    assert payload["usage"]["completion_tokens"] == 80
    assert payload["usage"]["total_tokens"] == 200
    assert payload["credits_charged"] == 200
    assert payload["estimated_cost_usd"] > 0.0
    assert str(payload.get("pricing_version") or "").strip()
    assert payload["stage"] == "candidate"


def test_normalize_usage_breakdown_accepts_input_output_token_shape():
    raw_usage = {
        "input_tokens": 45,
        "output_tokens": 30,
    }

    usage = normalize_usage_breakdown(raw_usage, request_count=2)

    assert usage.prompt_tokens == 45
    assert usage.completion_tokens == 30
    assert usage.total_tokens == 75
    assert usage.request_count == 2
