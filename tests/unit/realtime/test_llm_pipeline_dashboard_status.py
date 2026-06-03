from app.core.realtime.sagas import saga_health
from app.core.realtime.sagas.saga_health import LLMPipelineMetricsResponse, get_llm_pipeline_dashboard


async def test_llm_pipeline_dashboard_no_data_status(monkeypatch) -> None:
    async def _fake_metrics(window_hours: int = 24) -> LLMPipelineMetricsResponse:
        return LLMPipelineMetricsResponse(window_hours=window_hours, total_runs=0, groups=[])

    monkeypatch.setattr(saga_health, "get_llm_pipeline_metrics", _fake_metrics)

    response = await get_llm_pipeline_dashboard(window_hours=24)

    assert response.total_runs == 0
    assert response.status == "no_data"
    assert response.overall_status == "no_data"
