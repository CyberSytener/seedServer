"""SagaLLMPipelineAdapter — extracted from create_app() in main.py."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.core.llm.router import execute_action


class SagaLLMPipelineAdapter:
    def __init__(self, settings: Any = None) -> None:
        self.settings = settings

    @staticmethod
    def _extract_structured_output(output_text: str, output_schema: Dict[str, Any], format_hint: str) -> Any:
        text = (output_text or "").strip()
        if not text:
            return {}

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        # Soft recovery for markdown or mixed output when JSON is expected
        expects_json = bool(output_schema) or format_hint == "json_object"
        if expects_json and "{" in text and "}" in text:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                snippet = text[start : end + 1]
                try:
                    parsed = json.loads(snippet)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    logging.debug("Suppressed exception", exc_info=True)
        return text

    async def run_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        step_name = str((payload or {}).get("step") or "execute").strip().lower()
        step_inputs = (payload or {}).get("inputs") if isinstance((payload or {}).get("inputs"), dict) else {}
        mode = str((payload or {}).get("mode") or "fast").strip().lower() or "fast"
        policy = (payload or {}).get("policy") if isinstance((payload or {}).get("policy"), dict) else {}
        output_schema = (payload or {}).get("output_schema") if isinstance((payload or {}).get("output_schema"), dict) else {}
        format_hint = str((payload or {}).get("format_hint") or "json_object")

        text_payload = {
            "step": step_name,
            "inputs": step_inputs,
            "task_type": (payload or {}).get("task_type"),
            "output_schema": output_schema,
            "format_hint": format_hint,
        }
        input_text = json.dumps(text_payload, ensure_ascii=False, default=str)

        requested_provider = str(policy.get("provider") or "auto")
        requested_model = str(policy.get("model") or "auto")
        fallback_providers = [
            str(value).strip().lower()
            for value in (policy.get("fallback_providers") or [])
            if str(value).strip()
        ]
        provider_chain: list[str] = []
        if requested_provider and requested_provider.lower() not in {"", "auto", "default"}:
            provider_chain.append(requested_provider.lower())
        provider_chain.extend([value for value in fallback_providers if value not in provider_chain])
        if not provider_chain:
            provider_chain = ["auto", "openai", "gemini", "stub"]

        provider_tuning = policy.get("provider_tuning") if isinstance(policy.get("provider_tuning"), dict) else {}
        last_error: Optional[str] = None
        action_result = None
        used_provider = "auto"
        attempted_providers: list[str] = []

        for provider_name in provider_chain:
            tune = provider_tuning.get(provider_name) if isinstance(provider_tuning.get(provider_name), dict) else {}
            adapter_options: Dict[str, Any] = {
                "provider": provider_name,
                "model": str(tune.get("model") or requested_model or "auto"),
                "max_output_tokens": int(tune.get("max_output_tokens") or policy.get("max_output_tokens") or 1200),
                "temperature": float(tune.get("temperature") or policy.get("temperature") or 0.2),
                "top_p": float(tune.get("top_p") or policy.get("top_p") or 1.0),
                "response_format": "json" if (output_schema or format_hint == "json_object") else "text",
            }
            attempted_providers.append(provider_name)
            try:
                candidate_result = await execute_action(
                    action="ask",
                    input_text=input_text,
                    options=adapter_options,
                    mode=mode,
                )
                if str(getattr(candidate_result, "text", "") or "").strip():
                    action_result = candidate_result
                    used_provider = provider_name
                    break
                action_result = candidate_result
                used_provider = provider_name
            except Exception as step_error:
                last_error = str(step_error)
                continue

        if action_result is None:
            raise RuntimeError(last_error or "llm_pipeline_adapter_failed")

        output_text = str(action_result.text or "").strip()
        parsed_output: Any = self._extract_structured_output(output_text, output_schema, format_hint)

        usage = {
            "input_tokens": int(action_result.tokens_in or 0),
            "output_tokens": int(action_result.tokens_out or 0),
            "total_tokens": int((action_result.tokens_in or 0) + (action_result.tokens_out or 0)),
        }
        cost = {
            "units": float(action_result.cost_usd or 0.0),
            "provider": str(action_result.provider or "unknown"),
            "model": str(action_result.model or "unknown"),
        }
        return {
            "output": parsed_output,
            "usage": usage,
            "cost": cost,
            "model": {
                "provider": str(action_result.provider or used_provider or "unknown"),
                "model": str(action_result.model or "unknown"),
                "tier": str(policy.get("tier") or "unknown"),
            },
            "raw_response": output_text,
            "artifacts": {
                "attempted_providers": attempted_providers,
                "used_provider": used_provider,
                "structured_output": bool(output_schema or format_hint == "json_object"),
            },
        }

    async def generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)

    async def repair_loop(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.run_step(payload)
