from __future__ import annotations

import pytest

from app.sim.llm_stub import (
    DeterministicLLMPipelineStub,
    RealLLMPipelineAdapter,
    create_pipeline_adapter,
)


def test_create_pipeline_adapter_stub_mode_returns_stub() -> None:
    adapter = create_pipeline_adapter(llm_mode="stub")
    assert isinstance(adapter, DeterministicLLMPipelineStub)


def test_create_pipeline_adapter_real_mode_respects_explicit_provider_model(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    adapter = create_pipeline_adapter(
        llm_mode="real",
        provider="gemini",
        model="gemini-2.0-flash-lite",
    )
    assert isinstance(adapter, RealLLMPipelineAdapter)
    assert adapter.provider == "gemini"
    assert adapter.model == "gemini-2.0-flash-lite"


def test_create_pipeline_adapter_real_mode_prefers_cheap_gemini_default(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    monkeypatch.setenv("SEED_GEMINI_MODEL_CHEAP", "gemini-2.0-flash-lite")
    monkeypatch.delenv("SIM_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("SIM_LLM_MODEL", raising=False)

    adapter = create_pipeline_adapter(llm_mode="real")
    assert isinstance(adapter, RealLLMPipelineAdapter)
    assert adapter.provider == "gemini"
    assert adapter.model == "gemini-2.0-flash-lite"


def test_create_pipeline_adapter_rejects_unknown_provider(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    with pytest.raises(RuntimeError, match="SIM_LLM_PROVIDER must be one of"):
        create_pipeline_adapter(llm_mode="real", provider="anthropic")
