from app.core.realtime.sagas.saga_health import (
    LLMPipelineMetricsResponse,
    _build_mode_dashboard,
)


def test_build_mode_dashboard_returns_no_data_status() -> None:
    current = LLMPipelineMetricsResponse(window_hours=24, total_runs=0, groups=[])
    baseline = LLMPipelineMetricsResponse(window_hours=24, total_runs=0, groups=[])

    response = _build_mode_dashboard(current=current, baseline=baseline, window_hours=24, baseline_hours=24)

    assert response.overall_status == "no_data"
    assert response.modes == []
