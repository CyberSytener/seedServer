"""Core interface for async action execution."""

from __future__ import annotations

from typing import Protocol, Dict, Any, Optional

from app.core.llm.router import ActionResult


class ActionExecutor(Protocol):
    async def execute_action(
        self,
        action: str,
        input_text: str,
        options: Dict[str, Any],
        mode: str,
        persona_id: Optional[str] = None,
    ) -> ActionResult:
        ...
