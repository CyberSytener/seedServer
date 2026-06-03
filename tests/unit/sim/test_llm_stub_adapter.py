from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.realtime.engine.retry import RetryConfig, retry_with_backoff
from app.sim.llm_stub import DeterministicLLMPipelineStub, RealLLMPipelineAdapter, create_pipeline_adapter


@pytest.mark.asyncio
async def test_llm_stub_returns_deterministic_output():
    adapter = DeterministicLLMPipelineStub()
    payload = {
        "step": "execute",
        "inputs": {"prompt": "hello"},
        "task_type": "general",
        "mode": "fast",
    }

    first = await adapter.run_step(payload)
    second = await adapter.run_step(payload)

    assert first["output"]["answer"] == second["output"]["answer"]
    assert first["usage"]["total_tokens"] == 20


@pytest.mark.asyncio
async def test_llm_stub_supports_transient_retry():
    adapter = DeterministicLLMPipelineStub(fail_first_attempts=1)
    cfg = RetryConfig(max_attempts=3, initial_delay=0.1, max_delay=0.1, jitter_strategy="none")
    logger = Mock()

    async def call_once():
        return await adapter.run_step({"step": "execute", "inputs": {}, "task_type": "general", "mode": "fast"})

    sleep_mock = AsyncMock()
    with patch("app.core.realtime.engine.retry.asyncio.sleep", sleep_mock):
        result = await retry_with_backoff(call_once, cfg, "sim.llm", logger)

    assert result["output"]["step"] == "execute"
    assert sleep_mock.await_count == 1


def test_pipeline_adapter_defaults_to_stub(monkeypatch):
    monkeypatch.delenv("SIM_LLM_MODE", raising=False)
    adapter = create_pipeline_adapter()
    assert isinstance(adapter, DeterministicLLMPipelineStub)


@pytest.mark.asyncio
async def test_pipeline_adapter_real_mode_uses_mocked_llm_client(monkeypatch):
    monkeypatch.setenv("SIM_LLM_MODE", "real")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    adapter = create_pipeline_adapter(llm_mode="real")
    assert isinstance(adapter, RealLLMPipelineAdapter)

    with patch("app.sim.llm_stub.execute_llm_request", return_value="real-mode-response") as llm_mock:
        result = await adapter.run_step(
            {
                "step": "candidate",
                "task_type": "general",
                "mode": "fast",
                "inputs": {"prompt": "hello"},
            }
        )

    assert llm_mock.call_count == 1
    assert result["output"]["answer"] == "real-mode-response"
    assert result["model"]["provider"] == "gemini"
    assert result["model"]["tier"] == "real"


@pytest.mark.asyncio
async def test_pipeline_adapter_real_mode_consumes_runtime_metadata(monkeypatch):
    monkeypatch.setenv("SIM_LLM_MODE", "real")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")

    adapter = create_pipeline_adapter(llm_mode="real")
    assert isinstance(adapter, RealLLMPipelineAdapter)

    with patch(
        "app.sim.llm_stub.execute_llm_request",
        return_value={
            "text": "real-mode-metadata",
            "usage": {"prompt_tokens": 15, "completion_tokens": 5, "total_tokens": 20},
            "cost": {"estimated_cost_usd": 0.001},
            "pricing_version": "pricing.v-test",
            "ledger_event": {"pricing_version": "pricing.v-test"},
        },
    ):
        result = await adapter.run_step(
            {
                "step": "candidate",
                "task_type": "general",
                "mode": "fast",
                "inputs": {"prompt": "hello"},
            }
        )

    assert result["output"]["answer"] == "real-mode-metadata"
    assert result["usage"]["input_tokens"] == 15
    assert result["usage"]["output_tokens"] == 5
    assert result["usage"]["total_tokens"] == 20
    assert result["cost"]["units"] == 0.001
    assert result["artifacts"]["pricing_version"] == "pricing.v-test"
