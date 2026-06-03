from __future__ import annotations

import json
from unittest.mock import patch

from app.models.api import DiagnosticGenerateRequest
from app.services.diagnostic.engine import generate_diagnostic_items


def _diagnostic_payload() -> dict:
    return {
        "items": [
            {
                "id": "diag_cost_1",
                "taskType": "mcq",
                "prompt": "Pick the right translation for book",
                "context": {},
                "choices": ["libro", "mesa", "agua", "casa"],
                "answer": {"accepted": ["libro"], "normalize": "lower_trim"},
                "distractorsReason": [
                    {"choice": "mesa", "reasonTag": "semantic_neighbor"},
                    {"choice": "agua", "reasonTag": "topic_mismatch"},
                    {"choice": "casa", "reasonTag": "frequent_confusion"},
                ],
                "tags": {
                    "skill": "vocabulary",
                    "subskill": "nouns",
                    "topic": "basics",
                    "difficulty": 1.0,
                    "taskType": "mcq",
                    "cefrBand": "A1",
                    "languagePair": "English->Spanish",
                },
            }
        ]
    }


def test_diagnostic_generation_tracks_cost_for_retry_attempts():
    request = DiagnosticGenerateRequest(
        nativeLang="English",
        targetLang="Spanish",
        blueprint=[
            {
                "skill": "vocabulary",
                "subskill": "nouns",
                "topic": "basics",
                "difficulty": 1.0,
                "taskType": "mcq",
                "cefrBand": "A1",
            }
        ],
    )

    with (
        patch(
            "app.services.diagnostic.engine.execute_llm_request",
            side_effect=["not-json", json.dumps(_diagnostic_payload())],
        ),
        patch("app.services.diagnostic.engine.BillingMetrics.record_credit_ledger_event") as billing_mock,
    ):
        response = generate_diagnostic_items(
            request=request,
            user_id="u_cost_diag",
            optimize_mode=False,
            trace_id="trace_diag_1",
            session_id="session_diag_1",
            job_id="job_diag_1",
        )

    assert response.total_cost_usd > 0.0
    assert response.total_credits_charged > 0
    assert len(response.cost_breakdown) == 2
    assert response.cost_breakdown[0]["stage"] == "candidate"
    assert response.cost_breakdown[1]["stage"] == "retry_2"
    assert billing_mock.call_count == 2
