from __future__ import annotations

import os

import pytest

from app.sim.harness import run_simulation


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.real_smoke
def test_simulation_harness_real_mode_with_cheap_gemini(tmp_path) -> None:
    if str(os.getenv("SEED_TEST_ALLOW_REAL_LLM", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip("set SEED_TEST_ALLOW_REAL_LLM=1 to run real-provider smoke tests")

    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("real simulation smoke requires GEMINI_API_KEY")

    model = (
        os.getenv("SEED_GEMINI_MODEL_CHEAP")
        or os.getenv("SEED_GEMINI_MODEL_FAST")
        or "gemini-2.0-flash-lite"
    )

    report = run_simulation(
        output_dir=tmp_path,
        include_modes=True,
        llm_mode="real",
        llm_provider="gemini",
        llm_model=model,
    )

    assert report.passed is True

    s4 = next(item for item in report.scenarios if item.scenario_id == "S4")
    stage_refs = s4.artifacts.get("pipeline_stage_refs") or {}
    for stage in ("candidate", "validator", "final"):
        stage_ref = stage_refs.get(stage) or {}
        assert stage_ref.get("provider") == "gemini"
        assert stage_ref.get("model") == model
        artifact_ref = stage_ref.get("artifact_ref") or {}
        assert artifact_ref.get("uri")
        assert artifact_ref.get("sha256")
