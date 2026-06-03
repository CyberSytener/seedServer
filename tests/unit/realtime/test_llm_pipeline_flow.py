import os
from unittest.mock import AsyncMock

import pytest

from app.core.realtime.sagas.flows import LLMPipelineFlow
from app.core.realtime.sagas.flows import llm_pipeline as llm_pipeline_module
from app.core.realtime.sagas.orchestrator import SagaOrchestrator


@pytest.mark.asyncio
async def test_llm_pipeline_flow_succeeds_with_single_repair():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "Generate a short campaign summary",
        "task_type": "summary",
        "required_fields": ["title"],
        "mock_execute_output": {"answer": "Summary body"},
        "max_repairs": 1,
    }

    steps = []
    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-ok", payload, steps)

    assert result["status"] == "succeeded"
    final_response = result["result"]["final_response"]
    assert final_response["pipeline"] == "llm_pipeline@v1"
    assert final_response["stop_reason"] == "validation_passed"
    assert final_response["repair_attempts"] == 1
    assert str(final_response.get("pricing_version") or "").strip()
    assert final_response["policy"]["pricing_version"] == final_response["pricing_version"]
    assert isinstance(final_response.get("policy_snapshot"), dict)
    assert str(final_response["policy_snapshot"].get("fingerprint") or "").strip()

    step_names = [item.get("name") for item in steps]
    assert step_names == ["plan", "execute", "validate", "repair_loop", "format", "finalize"]


@pytest.mark.asyncio
async def test_llm_pipeline_flow_fails_when_repair_exhausted():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "Build strict output",
        "task_type": "strict_json",
        "required_fields": ["title"],
        "mock_execute_output": {"answer": "Missing required key"},
        "repair_strategy": "none",
        "max_repairs": 1,
    }

    steps = []
    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-fail", payload, steps)

    assert result["status"] == "succeeded"
    final_response = result["result"]["final_response"]
    assert final_response["stop_reason"] == "max_repairs_reached"
    assert final_response["repair_attempts"] == 0
    assert steps[-1]["name"] == "finalize"
    assert steps[-1]["status"] == "succeeded"

    dlq_messages = orchestrator.dlq.get_messages_by_flow("llm_pipeline")
    assert len(dlq_messages) == 0


@pytest.mark.asyncio
async def test_llm_pipeline_flow_fails_on_budget_exceeded_tokens():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "Generate strict result",
        "task_type": "summary",
        "required_fields": [],
        "budget": {"max_total_tokens": 100, "max_total_cost_units": 100, "max_wall_time_seconds": 120},
        "mock_usage": {
            "plan": {"total_tokens": 60, "cost_units": 0.1},
            "execute": {"total_tokens": 60, "cost_units": 0.1},
        },
    }

    steps = []
    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-budget-fail", payload, steps)

    assert result["status"] == "succeeded"
    final_response = result["result"]["final_response"]
    assert final_response["stop_reason"] == "budget_exceeded_tokens_predicted"
    assert final_response["stop_category"] == "budget"
    assert final_response["stop_severity"] == "error"
    assert isinstance(final_response.get("budget"), dict)
    execute_step = next(item for item in steps if item.get("name") == "execute")
    assert execute_step["meta"].get("predicted_budget_stop") is True

    dlq_messages = orchestrator.dlq.get_messages_by_flow("llm_pipeline")
    assert len(dlq_messages) == 0


@pytest.mark.asyncio
async def test_llm_pipeline_flow_fails_on_budget_exceeded_cost():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "Generate strict result",
        "task_type": "summary",
        "required_fields": [],
        "budget": {"max_total_tokens": 1000, "max_total_cost_units": 0.1, "max_wall_time_seconds": 120},
        "mock_usage": {
            "plan": {"total_tokens": 10, "cost_units": 0.06},
            "execute": {"total_tokens": 10, "cost_units": 0.06},
        },
    }

    steps = []
    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-budget-cost-fail", payload, steps)

    assert result["status"] == "succeeded"
    final_response = result["result"]["final_response"]
    assert final_response["stop_reason"] == "budget_exceeded_cost_predicted"
    assert final_response["stop_category"] == "budget"
    assert final_response["stop_severity"] == "error"
    assert isinstance(final_response.get("budget"), dict)


@pytest.mark.asyncio
async def test_llm_pipeline_flow_treats_zero_wall_time_budget_as_disabled():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "Generate strict result",
        "task_type": "summary",
        "required_fields": [],
        "budget": {"max_total_tokens": 10000, "max_total_cost_units": 100, "max_wall_time_seconds": 0},
    }

    steps = []
    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-budget-time-fail", payload, steps)

    assert result["status"] == "succeeded"
    final_response = result["result"]["final_response"]
    assert final_response["stop_reason"] == "validation_passed"
    assert final_response["stop_category"] == "success"
    assert final_response["stop_severity"] == "info"
    assert final_response["budget"]["max_wall_time_seconds"] is None
    assert isinstance(final_response.get("budget"), dict)


@pytest.mark.asyncio
async def test_llm_pipeline_step_idempotency_cache_hit_on_second_run():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "Repeatable generation",
        "task_type": "summary",
        "required_fields": ["title"],
        "mock_execute_output": {"answer": "Same answer each time"},
        "max_repairs": 1,
    }

    flow = LLMPipelineFlow(orchestrator)

    first_steps = []
    first = await flow.run("saga-llm-idem", payload, first_steps)
    assert first["status"] == "succeeded"
    assert first_steps[0]["meta"]["idempotency"]["cache_hit"] is False

    second_steps = []
    second = await flow.run("saga-llm-idem", payload, second_steps)
    assert second["status"] == "succeeded"
    assert second_steps[0]["meta"]["idempotency"]["cache_hit"] is True


@pytest.mark.asyncio
async def test_llm_pipeline_uses_task_policy_default_mode_and_repairs():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "High confidence legal copy",
        "task_type": "high_stakes_text",
        "required_fields": ["title"],
        "mock_execute_output": {"answer": "Needs repair"},
    }

    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-policy-default", payload, [])

    assert result["status"] == "succeeded"
    final_response = result["result"]["final_response"]
    assert final_response["mode"] == "best"
    assert final_response["repair_attempts"] == 1
    assert final_response["policy"]["quorum"]["enabled"] is True


@pytest.mark.asyncio
async def test_llm_pipeline_payload_mode_overrides_task_policy_mode():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "High confidence legal copy",
        "task_type": "high_stakes_text",
        "mode": "fast",
        "budget": {"max_total_tokens": 20000, "max_total_cost_units": 100, "max_wall_time_seconds": 120},
        "required_fields": ["title"],
        "mock_execute_output": {"answer": "Needs repair"},
    }

    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-policy-override", payload, [])

    assert result["status"] == "succeeded"
    final_response = result["result"]["final_response"]
    assert final_response["mode"] == "fast"


@pytest.mark.asyncio
async def test_llm_pipeline_schema_gate_with_output_schema_strict():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "Return strict shape",
        "task_type": "json_export",
        "output_schema": {
            "required": ["title", "score"],
            "properties": {
                "title": {"type": "string"},
                "score": {"type": "number"},
            },
        },
        "output_schema_strict": True,
        "mock_execute_output": {"title": "ok", "score": "not_number"},
        "max_repairs": 0,
    }

    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-schema", payload, [])

    assert result["status"] == "succeeded"
    final_response = result["result"]["final_response"]
    assert final_response["stop_reason"] in {"schema_type_mismatch", "schema_contract_violation", "max_repairs_reached"}


@pytest.mark.asyncio
async def test_llm_pipeline_quorum_produces_candidates_artifact():
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    payload = {
        "user_request": "High stakes output",
        "task_type": "high_stakes_text",
        "required_fields": ["title"],
        "mock_execute_output": {"answer": "candidate"},
    }

    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-quorum", payload, [])

    assert result["status"] == "succeeded"
    artifacts = result["result"]["final_response"]["artifacts"]
    assert isinstance(artifacts.get("candidates"), list)
    assert len(artifacts.get("candidates") or []) >= 2


@pytest.mark.asyncio
async def test_llm_pipeline_quorum_reports_per_candidate_timeout(monkeypatch):
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    async def _slow_execute(_payload):
        import asyncio
        await asyncio.sleep(0.2)
        return {"output": {"answer": "slow"}, "usage": {"total_tokens": 1}, "cost": {"units": 0.0}}

    class _SlowAdapter:
        async def execute(self, payload):
            return await _slow_execute(payload)

    orchestrator.adapters["llm_pipeline"] = _SlowAdapter()

    def _policy_override(**_kwargs):
        return {
            "policy_version": "test",
            "mode": "best",
            "budget": {"max_total_tokens": 10000, "max_total_cost_units": 1000, "max_wall_time_seconds": 120},
            "max_repairs": 0,
            "steps": {},
            "thresholds": {"pass_score": 85},
            "quorum": {"enabled": True, "candidates": 2, "concurrency": 2, "per_candidate_timeout_seconds": 0.01},
            "quorum_caps": {"max_candidates": 2, "max_concurrency": 2, "per_candidate_timeout_seconds": 0.01},
            "artifacts": {"enabled": True, "store_raw_responses": False},
            "tool_security": {},
            "model_tiers": {},
        }

    monkeypatch.setattr(llm_pipeline_module, "resolve_llm_policy", _policy_override)

    payload = {
        "user_request": "High stakes output",
        "task_type": "high_stakes_text",
    }

    flow = LLMPipelineFlow(orchestrator)
    steps = []
    await flow.run("saga-llm-timeout-observability", payload, steps)

    execute_meta = next(step["meta"] for step in steps if step.get("name") == "execute")
    artifacts = execute_meta.get("artifacts") or {}
    assert artifacts.get("timed_out_candidates") == 2
    assert isinstance(artifacts.get("candidate_latencies_ms"), list)
    assert len(artifacts.get("candidate_latencies_ms")) == 2


@pytest.mark.asyncio
async def test_llm_pipeline_trust_or_escalate_judge_trace_artifact(monkeypatch):
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    def _policy_override(**_kwargs):
        return {
            "policy_version": "test",
            "pricing_version": "pricing.test",
            "mode": "best",
            "budget": {"max_total_tokens": 10000, "max_total_cost_units": 1000, "max_wall_time_seconds": 120},
            "max_repairs": 0,
            "steps": {
                "validate": {
                    "tier": "balanced",
                    "ensemble": [
                        {
                            "kind": "llm_judge",
                            "tier": "balanced",
                            "trust_or_escalate": True,
                            "confidence_threshold": 0.99,
                            "escalate_tier": "powerful",
                        }
                    ],
                }
            },
            "thresholds": {"pass_score": 85},
            "quorum": {"enabled": True, "candidates": 2, "concurrency": 2},
            "quorum_caps": {"max_candidates": 2, "max_concurrency": 2},
            "artifacts": {"enabled": True, "store_raw_responses": False},
            "tool_security": {},
            "model_tiers": {},
        }

    monkeypatch.setattr(llm_pipeline_module, "resolve_llm_policy", _policy_override)

    payload = {
        "user_request": "High confidence legal copy",
        "task_type": "high_stakes_text",
        "mock_execute_output": {"title": "Ready"},
        "artifact_store_enabled": False,
    }

    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-judge-trace", payload, [])

    final_response = result["result"]["final_response"]
    judge_trace = (final_response.get("artifacts") or {}).get("judge_trace") or {}
    assert judge_trace.get("enabled") is True
    assert judge_trace.get("escalated") is True
    assert judge_trace.get("decision_source") == "escalated_judge"
    assert float(judge_trace.get("estimated_total_cost_units") or 0.0) > float(
        ((judge_trace.get("cheap_judge") or {}).get("estimated_cost_units") or 0.0)
    )
    assert isinstance(((final_response.get("artifacts") or {}).get("validator_report") or {}).get("judge_trace"), dict)


@pytest.mark.asyncio
async def test_llm_pipeline_writes_final_artifact_reference(tmp_path):
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={},
        async_mode=True,
    )
    orchestrator._update_saga_state = AsyncMock()

    os.environ["SEED_ARTIFACT_STORE_DIR"] = str(tmp_path)

    payload = {
        "user_request": "Generate a short campaign summary",
        "task_type": "summary",
        "required_fields": ["title"],
        "max_repairs": 1,
        "artifact_store_enabled": True,
    }

    flow = LLMPipelineFlow(orchestrator)
    result = await flow.run("saga-llm-artifact-ref", payload, [])

    final_artifacts = result["result"]["final_response"].get("artifacts") or {}
    final_ref = final_artifacts.get("final_response_ref") or {}
    policy_snapshot_ref = final_artifacts.get("policy_snapshot_ref") or {}
    assert final_ref.get("uri", "").startswith("artifact://")
    assert (tmp_path / str(final_ref.get("uri", "").replace("artifact://", ""))).name.endswith(".json")
    assert policy_snapshot_ref.get("uri", "").startswith("artifact://")
    assert str(policy_snapshot_ref.get("sha256") or "").strip()
