from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.gemini_client import GeminiClient

from app.services.saga_architect import resolve_model_tier

logger = logging.getLogger(__name__)


class TraceAnalyzer:
    def __init__(self, *, gemini_api_key: Optional[str] = None) -> None:
        self._gemini_key = gemini_api_key
        self._gemini: Optional[GeminiClient] = None
        if self._gemini_key:
            try:
                self._gemini = GeminiClient(api_key=self._gemini_key, default_model="gemini-2.0-flash-lite")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini client init failed for trace analyzer: %s", exc)

    async def analyze(
        self,
        *,
        execution_trace: List[Dict[str, Any]],
        performance: Optional[Dict[str, Any]] = None,
        blueprint: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        model_tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        tier_cfg = resolve_model_tier(model_tier or "powerful")
        model_name = tier_cfg["model"]

        if not self._gemini:
            return {
                "model_name": model_name,
                "model_tier": (model_tier or "powerful").lower(),
                "summary": self._fallback_summary(execution_trace, performance),
            }

        prompt = self._build_prompt(
            execution_trace=execution_trace,
            performance=performance,
            blueprint=blueprint,
            run_id=run_id,
        )
        try:
            response_text = await self._gemini.generate_content_async(prompt, model=model_name)
            return {
                "model_name": model_name,
                "model_tier": (model_tier or "powerful").lower(),
                "summary": response_text.strip(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Trace analysis failed: %s", exc)
            return {
                "model_name": model_name,
                "model_tier": (model_tier or "powerful").lower(),
                "summary": self._fallback_summary(execution_trace, performance),
            }

    @staticmethod
    def _build_prompt(
        *,
        execution_trace: List[Dict[str, Any]],
        performance: Optional[Dict[str, Any]],
        blueprint: Optional[Dict[str, Any]],
        run_id: Optional[str],
    ) -> str:
        payload = {
            "run_id": run_id,
            "execution_trace": execution_trace,
            "performance": performance or {},
            "blueprint": blueprint or {},
        }
        return (
            "You are a senior systems architect auditing a saga execution. "
            "Identify bottlenecks, logic errors, and remediation steps. "
            "Return a concise strategic summary (6-10 sentences), plain text.\n\n"
            f"Trace payload:\n{json.dumps(payload, indent=2, sort_keys=True)}\n"
        )

    @staticmethod
    def _fallback_summary(
        execution_trace: List[Dict[str, Any]],
        performance: Optional[Dict[str, Any]],
    ) -> str:
        failures = [entry for entry in execution_trace if entry.get("status") == "failed"]
        total = len(execution_trace)
        duration = None
        if isinstance(performance, dict):
            duration = performance.get("duration_ms")

        lines = [f"Steps executed: {total}."]
        if duration is not None:
            lines.append(f"Total duration: {duration}ms.")
        if failures:
            first = failures[0]
            lines.append(
                "Failure detected at step "
                f"{first.get('failed_step_id') or first.get('step')}, "
                f"block {first.get('failed_block') or first.get('block')}: "
                f"{first.get('error', 'unknown error')}."
            )
        else:
            lines.append("No failures detected in the execution trace.")
        return " ".join(lines)
