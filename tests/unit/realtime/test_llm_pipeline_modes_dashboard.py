from app.core.realtime.sagas.saga_health import (
    LLMPipelineMetricsGroup,
    LLMPipelineMetricsResponse,
    _build_mode_dashboard,
)


def test_build_mode_dashboard_computes_slo_and_cost_growth() -> None:
    current = LLMPipelineMetricsResponse(
        window_hours=24,
        total_runs=20,
        groups=[
            LLMPipelineMetricsGroup(
                task_type="json_export",
                mode="fast",
                policy_version="v1",
                total=10,
                pass_at_1=8,
                pass_at_final=9,
                repair_count=2,
                repair_attempts_total=3,
                avg_repairs_per_request=0.3,
                stop_reasons={"validation_passed": 9, "schema_invalid_json": 1},
                avg_cost_per_success=1.15,
            ),
            LLMPipelineMetricsGroup(
                task_type="high_stakes_text",
                mode="best",
                policy_version="v1",
                total=10,
                pass_at_1=7,
                pass_at_final=9,
                repair_count=4,
                repair_attempts_total=8,
                avg_repairs_per_request=0.8,
                stop_reasons={"validation_passed": 9, "quality_failed": 1},
                avg_cost_per_success=2.5,
            ),
        ],
    )

    baseline = LLMPipelineMetricsResponse(
        window_hours=24,
        total_runs=20,
        groups=[
            LLMPipelineMetricsGroup(
                task_type="json_export",
                mode="fast",
                policy_version="v1",
                total=10,
                pass_at_1=7,
                pass_at_final=9,
                repair_count=2,
                repair_attempts_total=4,
                avg_repairs_per_request=0.4,
                stop_reasons={"validation_passed": 9, "schema_invalid_json": 1},
                avg_cost_per_success=1.0,
            ),
            LLMPipelineMetricsGroup(
                task_type="high_stakes_text",
                mode="best",
                policy_version="v1",
                total=10,
                pass_at_1=8,
                pass_at_final=10,
                repair_count=3,
                repair_attempts_total=6,
                avg_repairs_per_request=0.6,
                stop_reasons={"validation_passed": 10},
                avg_cost_per_success=2.0,
            ),
        ],
    )

    response = _build_mode_dashboard(current=current, baseline=baseline, window_hours=24, baseline_hours=24)

    assert len(response.modes) == 2
    assert response.overall_status == "red"

    fast = next(item for item in response.modes if item.mode == "fast")
    assert fast.status == "red"
    assert fast.total_runs == 10
    assert fast.pass_at_1_rate == 0.8
    assert fast.pass_at_final_rate == 0.9
    assert fast.avg_repairs_per_request == 0.3
    assert round(fast.cost_growth_vs_baseline, 4) == 0.15
    assert fast.slo_compliance["pass_at_1_target_met"] is True
    assert fast.slo_compliance["pass_at_final_target_met"] is False
    assert fast.slo_compliance["avg_repairs_target_met"] is True
    assert fast.slo_compliance["cost_growth_target_met"] is True
    assert fast.slo_compliance["overall"] is False

    best = next(item for item in response.modes if item.mode == "best")
    assert best.status == "red"
    assert best.total_runs == 10
    assert best.pass_at_1_rate == 0.7
    assert best.pass_at_final_rate == 0.9
    assert best.avg_repairs_per_request == 0.8
    assert round(best.cost_growth_vs_baseline, 2) == 0.25
    assert best.slo_compliance["pass_at_1_target_met"] is False
    assert best.slo_compliance["pass_at_final_target_met"] is False
    assert best.slo_compliance["avg_repairs_target_met"] is False
    assert best.slo_compliance["cost_growth_target_met"] is True
    assert best.slo_compliance["overall"] is False
