from app.core.realtime.sagas import saga_health
from app.core.realtime.sagas.saga_health import (
    LLMPipelineMetricsGroup,
    LLMPipelineMetricsResponse,
    get_llm_pipeline_dashboard,
)


async def test_llm_pipeline_dashboard_includes_compliance_and_progress(monkeypatch) -> None:
    async def _fake_metrics(window_hours: int = 24) -> LLMPipelineMetricsResponse:
        return LLMPipelineMetricsResponse(
            window_hours=window_hours,
            total_runs=10,
            groups=[
                LLMPipelineMetricsGroup(
                    task_type="json_export",
                    mode="fast",
                    policy_version="v1",
                    total=10,
                    pass_at_1=8,
                    pass_at_final=9,
                    repair_count=3,
                    repair_attempts_total=4,
                    avg_repairs_per_request=0.4,
                    stop_reasons={"validation_passed": 9, "schema_invalid_json": 1},
                    avg_cost_per_success=0.5,
                )
            ],
        )

    monkeypatch.setattr(saga_health, "get_llm_pipeline_metrics", _fake_metrics)

    response = await get_llm_pipeline_dashboard(window_hours=24)

    assert response.total_runs == 10
    assert response.pass_at_1_rate == 0.8
    assert response.pass_at_final_rate == 0.9
    assert response.repair_rate == 0.3
    assert response.avg_repairs_per_request == 0.4
    assert response.status == "red"
    assert response.overall_status == "red"
    assert response.playbook_targets["pass_at_1_min"] == 0.7
    assert response.playbook_compliance["pass_at_1_target_met"] is True
    assert response.playbook_compliance["pass_at_final_target_met"] is False
    assert response.playbook_compliance["avg_repairs_target_met"] is True
    assert response.playbook_compliance["overall"] is False
    assert response.implementation_progress["phase_4_metrics_api_dashboard"] is True
    assert response.test_snapshot["status"] == "green"
    assert response.test_snapshot["total_passed"] == 12
