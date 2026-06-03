"""Audit schema models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .actions import Action, ActionResult
from .client import ClientActionConfirm, ClientMessage
from .server import ModelFinal, ModelPartial


class ConversationTurn(BaseModel):
    """Single conversation turn with audit trail."""

    turn_id: str
    session_id: str
    user_id: Optional[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    client_message: Optional[ClientMessage] = None
    model_response: List[Union[ModelPartial, ModelFinal]] = Field(default_factory=list)
    actions_invoked: List[Action] = Field(default_factory=list)
    action_results: List[ActionResult] = Field(default_factory=list)
    user_confirmations: List[ClientActionConfirm] = Field(default_factory=list)

    model_used: str
    tokens_used: int = 0
    latency_ms: Optional[int] = None

    model_config: ConfigDict = ConfigDict(
        protected_namespaces=(),
        json_schema_extra={
            "description": "Complete audit record of one conversation turn",
        },
    )
