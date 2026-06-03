from app.core.realtime.sagas.saga_health import _aggregate_llm_pipeline_metrics


def test_aggregate_llm_pipeline_metrics_groups_and_rates() -> None:
    rows = [
        {
            "result": {
                "final_response": {
                    "task_type": "summarization",
                    "mode": "balanced",
                    "policy": {"version": "v2"},
                    "stop_reason": "validation_passed",
                    "repair_attempts": 0,
                    "budget": {"consumed_cost_units": 0.3},
                }
            }
        },
        {
            "result": {
                "final_response": {
                    "task_type": "summarization",
                    "mode": "balanced",
                    "policy": {"version": "v2"},
                    "stop_reason": "validation_passed",
                    "repair_attempts": 2,
                    "budget": {"consumed_cost_units": 0.7},
                }
            }
        },
        {
            "result": {
                "final_response": {
                    "task_type": "translation",
                    "mode": "strict",
                    "policy": {"version": "v1"},
                    "stop_reason": "schema_invalid_json",
                    "repair_attempts": 1,
                    "budget": {"consumed_cost_units": 0.2},
                }
            }
        },
    ]

    response = _aggregate_llm_pipeline_metrics(rows, window_hours=24)

    assert response.total_runs == 3
    assert len(response.groups) == 2

    summary_group = next(
        g for g in response.groups if g.task_type == "summarization" and g.mode == "balanced" and g.policy_version == "v2"
    )
    assert summary_group.total == 2
    assert summary_group.pass_at_1 == 1
    assert summary_group.pass_at_final == 2
    assert summary_group.repair_count == 1
    assert summary_group.repair_attempts_total == 2
    assert summary_group.avg_repairs_per_request == 1.0
    assert summary_group.stop_reasons["validation_passed"] == 2
    assert summary_group.avg_cost_per_success == 0.5

    strict_group = next(
        g for g in response.groups if g.task_type == "translation" and g.mode == "strict" and g.policy_version == "v1"
    )
    assert strict_group.total == 1
    assert strict_group.pass_at_1 == 0
    assert strict_group.pass_at_final == 0
    assert strict_group.repair_count == 1
    assert strict_group.repair_attempts_total == 1
    assert strict_group.avg_repairs_per_request == 1.0
    assert strict_group.stop_reasons["schema_invalid_json"] == 1
    assert strict_group.avg_cost_per_success == 0.0


def test_aggregate_llm_pipeline_metrics_skips_invalid_records() -> None:
    rows = [
        {"result": None},
        {"result": {"final_response": "not-a-dict"}},
        {"result": {}},
    ]

    response = _aggregate_llm_pipeline_metrics(rows, window_hours=12)

    assert response.window_hours == 12
    assert response.total_runs == 0
    assert response.groups == []
