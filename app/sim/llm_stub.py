from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any, Dict

from app.core.llm.router import execute_llm_request
from app.core.realtime.adapters.errors import TransientAdapterError
from app.settings import get_settings


class DeterministicLLMPipelineStub:
    """Deterministic stub implementing the runtime LLM pipeline adapter shape."""

    def __init__(self, *, fail_first_attempts: int = 0) -> None:
        self.fail_first_attempts = max(0, int(fail_first_attempts))
        self._attempts = defaultdict(int)

    async def run_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        step_name = str((payload or {}).get("step") or "execute")
        self._attempts[step_name] += 1

        if self._attempts[step_name] <= self.fail_first_attempts:
            raise TransientAdapterError(f"simulated_transient_error:{step_name}:{self._attempts[step_name]}")

        inputs = (payload or {}).get("inputs") if isinstance((payload or {}).get("inputs"), dict) else {}
        task_type = str((payload or {}).get("task_type") or "general")
        mode = str((payload or {}).get("mode") or "fast")

        output = {
            "answer": f"stub:{step_name}:{task_type}:{mode}",
            "step": step_name,
            "attempt": self._attempts[step_name],
            "echo": json.dumps(inputs, ensure_ascii=False, sort_keys=True, default=str)[:256],
        }

        return {
            "output": output,
            "usage": {
                "input_tokens": 8,
                "output_tokens": 12,
                "total_tokens": 20,
            },
            "cost": {
                "units": 0.01,
                "provider": "sim",
                "model": "deterministic-llm",
            },
            "model": {
                "provider": "sim",
                "model": "deterministic-llm",
                "tier": "test",
            },
            "raw_response": json.dumps(output, ensure_ascii=False),
            "artifacts": {
                "stub": True,
                "step": step_name,
                "attempt": self._attempts[step_name],
            },
            "candidates": [],
        }

    async def generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def repair_loop(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def format(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)


class RealLLMPipelineAdapter:
    """Real LLM adapter for simulation harness, using production router path."""

    def __init__(self, *, provider: str, model: str, timeout_sec: int = 45, max_attempts: int = 3) -> None:
        self.provider = provider
        self.model = model
        self.timeout_sec = timeout_sec
        self.max_attempts = max(1, int(max_attempts))
        self._attempts = defaultdict(int)

    async def run_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        step_name = str((payload or {}).get("step") or "execute")
        self._attempts[step_name] += 1
        inputs = (payload or {}).get("inputs") if isinstance((payload or {}).get("inputs"), dict) else {}
        task_type = str((payload or {}).get("task_type") or "general")
        mode = str((payload or {}).get("mode") or "fast")

        system_prompt = (
            "You are running Seed simulation harness in real LLM mode. "
            "Return concise plain text suitable for candidate/validator/final pipeline stages."
        )
        user_prompt = json.dumps(
            {
                "stage": step_name,
                "task_type": task_type,
                "mode": mode,
                "inputs": inputs,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        last_error: Exception | None = None
        runtime_result: Dict[str, Any] | str = ""
        for _ in range(self.max_attempts):
            try:
                runtime_result = execute_llm_request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    provider=self.provider,
                    model=self.model,
                    timeout_sec=self.timeout_sec,
                    max_tokens=512,
                    return_metadata=True,
                    endpoint="/sim/llm_pipeline",
                    feature="sim_real_llm",
                    stage=step_name,
                    attempt=self._attempts[step_name],
                )
                last_error = None
                break
            except Exception as exc:
                last_error = exc

        if last_error is not None:
            raise TransientAdapterError(f"real_llm_failed:{step_name}:{last_error}")

        result_text = str((runtime_result or {}).get("text") or "").strip() if isinstance(runtime_result, dict) else str(runtime_result or "").strip()
        runtime_usage = (runtime_result or {}).get("usage") if isinstance(runtime_result, dict) else {}
        usage_input = int((runtime_usage or {}).get("prompt_tokens") or (runtime_usage or {}).get("input_tokens") or 0)
        usage_output = int((runtime_usage or {}).get("completion_tokens") or (runtime_usage or {}).get("output_tokens") or 0)
        usage_total = int((runtime_usage or {}).get("total_tokens") or (usage_input + usage_output))
        if usage_total <= 0:
            usage_input = max(1, len(system_prompt + user_prompt) // 4)
            usage_output = max(1, len(result_text) // 4)
            usage_total = usage_input + usage_output

        ledger_event = (runtime_result or {}).get("ledger_event") if isinstance(runtime_result, dict) else {}
        cost = (runtime_result or {}).get("cost") if isinstance(runtime_result, dict) else {}
        estimated_cost = float((cost or {}).get("estimated_cost_usd") or (ledger_event or {}).get("estimated_cost_usd") or 0.0)
        pricing_version = str((runtime_result or {}).get("pricing_version") or (ledger_event or {}).get("pricing_version") or "") if isinstance(runtime_result, dict) else ""

        output = {
            "answer": result_text,
            "step": step_name,
            "attempt": self._attempts[step_name],
            "echo": json.dumps(inputs, ensure_ascii=False, sort_keys=True, default=str)[:256],
        }

        return {
            "output": output,
            "usage": {
                "input_tokens": usage_input,
                "output_tokens": usage_output,
                "total_tokens": usage_total,
            },
            "cost": {
                "units": estimated_cost,
                "provider": self.provider,
                "model": self.model,
            },
            "model": {
                "provider": self.provider,
                "model": self.model,
                "tier": "real",
            },
            "raw_response": result_text,
            "artifacts": {
                "stub": False,
                "real": True,
                "step": step_name,
                "attempt": self._attempts[step_name],
                "pricing_version": pricing_version,
                "ledger_event": ledger_event if isinstance(ledger_event, dict) else {},
            },
            "candidates": [],
        }

    async def generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def repair_loop(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def format(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)


def _resolve_llm_mode(llm_mode: str | None = None) -> str:
    mode = str(llm_mode or os.getenv("SIM_LLM_MODE", "stub")).strip().lower()
    return "real" if mode == "real" else "stub"


def _resolve_real_provider_model(
    *,
    provider_override: str | None = None,
    model_override: str | None = None,
) -> tuple[str, str]:
    settings = get_settings()
    provider = str(provider_override or os.getenv("SIM_LLM_PROVIDER", "")).strip().lower()
    model = str(model_override or os.getenv("SIM_LLM_MODEL", "")).strip()
    cheap_gemini = (
        os.getenv("SEED_GEMINI_MODEL_CHEAP")
        or os.getenv("SEED_GEMINI_MODEL_FAST")
        or settings.gemini_model_fast
        or "gemini-2.0-flash-lite"
    )

    if provider in {"gemini", "google"}:
        if not settings.gemini_api_key:
            raise RuntimeError("SIM real mode with provider=gemini requires GEMINI_API_KEY")
        return "gemini", model or cheap_gemini

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("SIM real mode with provider=openai requires OPENAI_API_KEY")
        return "openai", model or settings.openai_model_fast or "gpt-4.1-mini"

    if provider:
        raise RuntimeError("SIM_LLM_PROVIDER must be one of: gemini, openai")

    if model:
        model_lower = model.lower()
        if model_lower.startswith("gemini"):
            if not settings.gemini_api_key:
                raise RuntimeError("SIM real mode model=gemini* requires GEMINI_API_KEY")
            return "gemini", model
        if model_lower.startswith("gpt"):
            if not settings.openai_api_key:
                raise RuntimeError("SIM real mode model=gpt* requires OPENAI_API_KEY")
            return "openai", model

    if settings.gemini_api_key:
        return "gemini", model or cheap_gemini
    if settings.openai_api_key:
        return "openai", model or settings.openai_model_fast or "gpt-4.1-mini"
    raise RuntimeError("SIM_LLM_MODE=real requires GEMINI_API_KEY or OPENAI_API_KEY")


def create_pipeline_adapter(
    *,
    llm_mode: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> DeterministicLLMPipelineStub | RealLLMPipelineAdapter:
    mode = _resolve_llm_mode(llm_mode)
    if mode == "real":
        resolved_provider, resolved_model = _resolve_real_provider_model(
            provider_override=provider,
            model_override=model,
        )
        return RealLLMPipelineAdapter(provider=resolved_provider, model=resolved_model)
    return DeterministicLLMPipelineStub()
