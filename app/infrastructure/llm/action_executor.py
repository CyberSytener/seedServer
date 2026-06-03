"""Infrastructure implementation of the core action executor interface."""

from __future__ import annotations

from typing import Dict, Any, Optional

from app.core.interfaces.action_executor import ActionExecutor
from app.core.llm.router import ActionResult, execute_action


class InfrastructureActionExecutor(ActionExecutor):
    async def execute_action(
        self,
        action: str,
        input_text: str,
        options: Dict[str, Any],
        mode: str,
        persona_id: Optional[str] = None,
    ) -> ActionResult:
        return await execute_action(action, input_text, options, mode, persona_id)
