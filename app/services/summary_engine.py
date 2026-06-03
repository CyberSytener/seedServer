from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.core.gemini_client import GeminiClient

from app.services.saga_architect import resolve_model_tier
from app.services.saga_reporter import SagaReporter

logger = logging.getLogger(__name__)


class SummaryEngine:
    def __init__(self, *, gemini_api_key: Optional[str] = None) -> None:
        self._gemini_key = gemini_api_key
        self._gemini: Optional[GeminiClient] = None
        if self._gemini_key:
            try:
                self._gemini = GeminiClient(api_key=self._gemini_key, default_model="gemini-2.0-flash-lite")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini client init failed for summary engine: %s", exc)

    async def summarize(
        self,
        *,
        execution_result: Dict[str, Any],
        model_tier: Optional[str] = None,
        include_fix: bool = True,
    ) -> Dict[str, Any]:
        tier_cfg = resolve_model_tier(model_tier)
        model_name = tier_cfg["model"]

        reporter = SagaReporter(gemini_api_key=self._gemini_key, gemini_model=model_name)
        summary = await reporter.generate_summary(execution_result)

        fix = None
        if include_fix:
            fix = await self._suggest_fix(execution_result, model_name)

        return {
            "model_name": model_name,
            "model_tier": (model_tier or "").lower() or None,
            "summary": summary,
            "fix_suggestion": fix,
        }

    async def _suggest_fix(self, execution_result: Dict[str, Any], model_name: str) -> Optional[str]:
        failed_step = execution_result.get("failed_step_id")
        failed_block = execution_result.get("failed_block")
        error = execution_result.get("error") or ""
        trace = execution_result.get("execution_trace") or []

        if not (failed_step or error):
            return None

        prompt = (
            "You are a senior engineer reviewing a failed saga run. "
            "Given the failed step and error, propose a concise fix. "
            "If the issue is in a block, suggest changes to the block logic or inputs. "
            "Return 2-4 bullet points, plain text.\n\n"
            f"Failed step: {failed_step}\n"
            f"Failed block: {failed_block}\n"
            f"Error: {error}\n"
            f"Trace: {trace}\n"
        )

        if not self._gemini:
            return None

        try:
            text = await self._gemini.generate_content_async(prompt, model=model_name)
            return text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Summary fix generation failed: %s", exc)
            return None
