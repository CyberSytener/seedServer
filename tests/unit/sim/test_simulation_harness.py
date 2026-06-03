from __future__ import annotations

import pytest

from app.sim.harness import run_simulation


@pytest.mark.sim
def test_simulation_harness_runs_all_scenarios(tmp_path):
    report = run_simulation(output_dir=tmp_path, include_modes=True)

    assert report.passed is True
    assert report.scenario_count == 4
    assert report.failed_count == 0
    assert report.schema_id == "seed.simulation.report.v2"
    assert isinstance(report.run_metadata, dict)
    assert report.run_metadata.get("harness_version") == "2.0"
    assert report.run_metadata.get("runner") == "app.sim.run"
    assert report.run_metadata.get("output_dir")


@pytest.mark.sim
def test_simulation_harness_s1_verifies_idempotency_and_correlation(tmp_path):
    report = run_simulation(output_dir=tmp_path, include_modes=False)
    s1 = next(item for item in report.scenarios if item.scenario_id == "S1")

    assertion_map = {item.key: item.passed for item in s1.assertions}
    assert assertion_map["actions.idempotent.same_job"] is True
    assert assertion_map["worker.single_claim"] is True
    assert assertion_map["correlation.job.options"] is True
    assert assertion_map["correlation.job.events"] is True


@pytest.mark.sim
def test_simulation_harness_s4_includes_pipeline_artifact_refs(tmp_path):
    report = run_simulation(output_dir=tmp_path, include_modes=True)
    s4 = next(item for item in report.scenarios if item.scenario_id == "S4")

    assertion_map = {item.key: item.passed for item in s4.assertions}
    for stage in ("candidate", "validator", "final"):
        assert assertion_map[f"modes.pipeline.{stage}.artifact_ref"] is True
        assert assertion_map[f"modes.pipeline.{stage}.model_meta"] is True
        assert assertion_map[f"modes.pipeline.{stage}.usage_meta"] is True
        assert assertion_map[f"modes.pipeline.{stage}.cost_meta"] is True

    assert assertion_map["modes.pipeline.final.budget_snapshot"] is True
    assert assertion_map["modes.pipeline.final.policy_snapshot"] is True
    assert assertion_map["modes.pipeline.final.artifact_ref"] is True
    assert assertion_map["modes.pipeline.final.policy_artifact_ref"] is True
    assert assertion_map["modes.pipeline.parity.usage_budget"] is True
    assert assertion_map["modes.pipeline.parity.cost_credits"] is True

    stage_refs = s4.artifacts.get("pipeline_stage_refs")
    assert isinstance(stage_refs, dict)
    for stage in ("candidate", "validator", "final"):
        assert stage in stage_refs
        assert stage_refs[stage].get("provider")
        assert stage_refs[stage].get("model")
        usage = stage_refs[stage].get("usage") or {}
        cost = stage_refs[stage].get("cost") or {}
        assert isinstance(usage, dict)
        assert isinstance(cost, dict)
        assert "total_tokens" in usage
        assert "units" in cost
        artifact_ref = stage_refs[stage].get("artifact_ref") or {}
        assert artifact_ref.get("uri")
        assert artifact_ref.get("sha256")

    budget_snapshot = s4.artifacts.get("pipeline_budget_snapshot") or {}
    policy_snapshot = s4.artifacts.get("pipeline_policy_snapshot") or {}
    pipeline_artifact_refs = s4.artifacts.get("pipeline_artifact_refs") or {}
    usage_totals = s4.artifacts.get("pipeline_usage_totals") or {}
    credit_totals = s4.artifacts.get("pipeline_credit_totals") or {}

    assert "consumed_tokens" in budget_snapshot
    assert "consumed_cost_units" in budget_snapshot
    assert policy_snapshot.get("policy_version")
    assert policy_snapshot.get("pricing_version")
    assert policy_snapshot.get("fingerprint")
    assert (pipeline_artifact_refs.get("final_response_ref") or {}).get("uri")
    assert (pipeline_artifact_refs.get("policy_snapshot_ref") or {}).get("uri")
    assert "total_tokens" in usage_totals
    assert "total_cost_units" in usage_totals
    assert "estimated_credits" in credit_totals


@pytest.mark.sim
def test_simulation_report_to_dict_keeps_backward_compatible_fields(tmp_path):
    report = run_simulation(output_dir=tmp_path, include_modes=False)
    payload = report.to_dict()

    assert "run_id" in payload
    assert "started_at" in payload
    assert "finished_at" in payload
    assert "duration_ms" in payload
    assert "passed" in payload
    assert "scenario_count" in payload
    assert "passed_count" in payload
    assert "failed_count" in payload
    assert "scenarios" in payload
    assert "metadata" in payload
    assert "schema_id" in payload
    assert "run_metadata" in payload


@pytest.mark.sim
def test_simulation_harness_records_llm_override_metadata(tmp_path):
    report = run_simulation(
        output_dir=tmp_path,
        include_modes=True,
        llm_mode="stub",
        llm_provider="gemini",
        llm_model="gemini-2.0-flash-lite",
    )

    assert report.metadata.get("llm_provider") == "gemini"
    assert report.metadata.get("llm_model") == "gemini-2.0-flash-lite"
    assert report.run_metadata.get("llm_provider") == "gemini"
    assert report.run_metadata.get("llm_model") == "gemini-2.0-flash-lite"
