"""Server message schema models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .actions import Action, ActionResult


class ModelPartial(BaseModel):
    """Streaming partial response from model."""

    type: str = Field(default="model.partial")
    chunk: str = Field(description="Partial text/token chunk")
    delta: Optional[str] = None

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "model.partial",
            "chunk": "Here's a great CV template for",
            "delta": " a great CV template",
        }
    })


class ModelFinal(BaseModel):
    """Final model response."""

    type: str = Field(default="model.final")
    content: str = Field(description="Complete response content")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "model.final",
            "content": "Your CV is ready! Here are 3 variations...",
            "metadata": {
                "tokens_used": 342,
                "model": "gemini-2.0-flash",
            },
        }
    })


class ModelInvokeAction(BaseModel):
    """Model requests to invoke an action (NOT executed by model)."""

    type: str = Field(default="model.invoke_action")
    action: Action = Field(description="Action to invoke")

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "model.invoke_action",
            "action": {
                "name": "search_listings",
                "id": "act_12345",
                "params": {
                    "location": "Oslo, Norway",
                    "price_min": 250000,
                },
                "metadata": {
                    "session_id": "sess_9876",
                    "confidence": 0.92,
                    "requires_user_confirmation": False,
                },
            },
        }
    })


class SystemEvent(BaseModel):
    """System-level event: auth, error, warning."""

    type: str = Field(default="system.event")
    level: str = Field(description="error, warning, info")
    code: str = Field(description="Event code: auth_failed, rate_limit, etc.")
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "system.event",
            "level": "error",
            "code": "auth_failed",
            "message": "Invalid session token",
            "details": {"session_id": "sess_9876"},
        }
    })


class SagaUpdate(BaseModel):
    """Saga state update for clients."""

    type: str = Field(default="saga.update")
    session_id: str
    saga_id: str
    saga_type: Optional[str] = None
    state: str
    steps: Optional[List[Dict[str, Any]]] = None
    result: Optional[Any] = None
    updated_at: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "saga.update",
            "session_id": "sess_9876",
            "saga_id": "saga_12345",
            "saga_type": "job_search",
            "state": "waiting_confirm",
            "steps": [{"name": "step_name", "status": "succeeded", "timestamp": "..."}],
            "result": {},
            "updated_at": "2026-01-31T12:34:56Z",
            "timestamp": "2026-01-31T12:34:56Z",
        }
    })


class SagaStatusResponse(BaseModel):
    """Saga status response (server → client)."""

    type: str = Field(default="saga.status")
    session_id: str
    saga_id: str
    saga_type: Optional[str] = None
    state: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None
    result: Optional[Any] = None
    updated_at: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "saga.status",
            "session_id": "sess_9876",
            "saga_id": "saga_12345",
            "saga_type": "job_search",
            "state": "in_progress",
            "steps": [{"name": "step_name", "status": "succeeded", "timestamp": "..."}],
            "result": {},
            "updated_at": "2026-01-31T12:34:56Z",
        }
    })


ServerMessageUnion = Union[
    ModelPartial,
    ModelFinal,
    ModelInvokeAction,
    ActionResult,
    SystemEvent,
    SagaUpdate,
    SagaStatusResponse,
]
