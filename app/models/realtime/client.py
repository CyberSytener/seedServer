"""Client message schema models."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .actions import Action


class ClientMessage(BaseModel):
    """User message: text, audio reference, or file."""

    type: str = Field(default="client.message")
    text: Optional[str] = None
    audio_ref: Optional[str] = None
    file_ref: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("text", "audio_ref", "file_ref")
    @classmethod
    def at_least_one_content(cls, value):
        return value

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "client.message",
            "text": "Помоги составить CV под позицию Senior JS dev",
            "metadata": {"language": "ru"},
        }
    })


class ClientCommand(BaseModel):
    """UI/system command: stop, regenerate, etc."""

    type: str = Field(default="client.command")
    command: str = Field(description="Command type: stop, regenerate, upload_resume, etc.")
    action_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "client.command",
            "command": "stop",
            "action_id": "act_12345",
        }
    })


class ClientActionConfirm(BaseModel):
    """User confirms an action (booking, email, etc.)."""

    type: str = Field(default="client.action.confirm")
    action_id: str = Field(description="ID of action to confirm/reject")
    confirm: bool = Field(description="True to confirm, False to reject")
    reason: Optional[str] = None

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "client.action.confirm",
            "action_id": "act_12345",
            "confirm": True,
            "reason": "Looks good",
        }
    })


class ActionInvoke(BaseModel):
    """Client invokes an action (FastAPI WS variant)."""

    type: str = Field(default="action.invoke")
    action: Action = Field(description="Action to invoke")

    model_config: ConfigDict = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "type": "action.invoke",
                "action": {
                    "name": "job_search",
                    "id": "act_12345",
                    "params": {"keywords": "Python Developer"},
                    "metadata": {"session_id": "sess_9876", "requires_user_confirmation": False},
                },
                "criteria": {"location": "Berlin"},
            }
        },
    )


class ActionConfirm(BaseModel):
    """Client confirms an action (FastAPI WS variant)."""

    type: str = Field(default="action.confirm")
    action_id: str = Field(description="ID of action to confirm/reject")
    confirm: bool = Field(description="True to confirm, False to reject")
    reason: Optional[str] = None

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "action.confirm",
            "action_id": "act_12345",
            "confirm": True,
            "reason": "Looks good",
        }
    })


class ActionCancel(BaseModel):
    """Client cancels an action (FastAPI WS variant)."""

    type: str = Field(default="action.cancel")
    action_id: str = Field(description="ID of action to cancel")
    reason: Optional[str] = None

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "action.cancel",
            "action_id": "act_12345",
            "reason": "User cancelled",
        }
    })


class SagaStatusRequest(BaseModel):
    """Client requests saga status (FastAPI WS variant)."""

    type: str = Field(default="saga.status")
    saga_id: str = Field(description="Saga ID to query")

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "saga.status",
            "saga_id": "saga_12345",
        }
    })


ClientMessageUnion = Union[
    ClientMessage,
    ClientCommand,
    ClientActionConfirm,
    ActionInvoke,
    ActionConfirm,
    ActionCancel,
    SagaStatusRequest,
]
