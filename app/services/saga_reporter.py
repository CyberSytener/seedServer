from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class SagaReporter:
    """Generate human-readable summaries from saga execution traces."""

    def __init__(
        self,
        *,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
    ) -> None:
        self._gemini_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        self._gemini_model = gemini_model or os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-2.0-flash-lite"
        self._gemini: Optional[GeminiClient] = None
        if self._gemini_key:
            try:
                self._gemini = GeminiClient(api_key=self._gemini_key, default_model=self._gemini_model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini client init failed for saga reporter: %s", exc)

    async def generate_summary(self, execution_result: Dict[str, Any]) -> str:
        trace = execution_result.get("execution_trace") or []
        result = execution_result.get("result") or {}
        status = execution_result.get("status", "unknown")
        mode = execution_result.get("execution_mode", "LIVE")

        tech_summary = self._build_technical_summary(status, mode, trace, result)

        if not self._gemini:
            logger.info("No GEMINI_API_KEY; returning technical summary only")
            return tech_summary

        try:
            return await self._generate_ai_summary(tech_summary)
        except Exception as exc:
            logger.warning("AI summary generation failed: %s", exc)
            return tech_summary

    @staticmethod
    def _build_technical_summary(
        status: str,
        mode: str,
        trace: List[Dict[str, Any]],
        result: Dict[str, Any],
    ) -> str:
        lines: List[str] = []
        lines.append(f"Status: {status} | Mode: {mode}")
        lines.append(f"Steps executed: {len(trace)}")

        for entry in trace:
            step = entry.get("step", "?")
            block = entry.get("block", "?")
            elapsed = entry.get("elapsed_sec", 0)
            dry = " [DRY_RUN]" if entry.get("dry_run") else ""
            outputs = entry.get("output_keys") or []
            lines.append(f"  - {step} ({block}): {elapsed}s, outputs={outputs}{dry}")

        job_count = 0
        jobs = result.get("jobs")
        if isinstance(jobs, list):
            job_count = len(jobs)

        scored_count = result.get("scored_count") or 0
        source_counts = result.get("source_counts") or {}
        notified = result.get("notified_count") or 0

        if job_count or source_counts:
            lines.append(f"Jobs found: {job_count}")
            for source, count in sorted(source_counts.items()):
                lines.append(f"  - {source}: {count}")

        if scored_count:
            lines.append(f"Jobs scored: {scored_count}")

        if notified:
            lines.append(f"Notifications sent: {notified}")

        return "\n".join(lines)

    async def _generate_ai_summary(self, technical_summary: str) -> str:
        prompt = (
            "You are a helpful assistant explaining automation results to a non-technical user.\n"
            "Given the following technical execution log, write a friendly 2-4 sentence summary.\n"
            "Focus on what happened, what was found, and the outcome.\n"
            "If this was a DRY_RUN, mention it was a simulation.\n\n"
            f"Technical log:\n{technical_summary}\n\n"
            "Write your summary now (plain text, no markdown):"
        )

        if not self._gemini:
            raise RuntimeError("Gemini SDK is not available")
        response_text = await self._gemini.generate_content_async(prompt, model=self._gemini_model)
        return response_text.strip()
