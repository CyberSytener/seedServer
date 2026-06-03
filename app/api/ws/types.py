"""
WebSocket message types and protocols for STEP 3.

Gateway is a "dumb pipe" - these types carry semantics from:
- client.message: user text input
- model.partial: streaming response chunks
- model.final: complete response
- model.invoke_action: embedded action request
- action.result: action execution result from router

No business logic here - just message transport.
"""

from enum import Enum
from typing import Any, Optional, Dict, List
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Message types crossing the gateway."""
    
    # Client → Gateway → Router
    CLIENT_MESSAGE = "client.message"
    
    # Router → Gateway → Client (streaming)
    MODEL_PARTIAL = "model.partial"
    MODEL_FINAL = "model.final"
    MODEL_INVOKE_ACTION = "model.invoke_action"
    
    # Router → Gateway → Client (action completion)
    ACTION_RESULT = "action.result"
    ACTION_DEFERRED = "action.deferred"

    # Saga updates (STEP 4)
    SAGA_UPDATE = "saga.update"
    
    # Session management
    SESSION_CONNECTED = "session.connected"
    SESSION_RECONNECTED = "session.reconnected"
    SESSION_DISCONNECT = "session.disconnect"
    SESSION_ERROR = "session.error"


class ClientMessage(BaseModel):
    """Client sends text message."""
    type: MessageType = MessageType.CLIENT_MESSAGE
    session_id: str
    user_id: str
    content: str
    trace_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelPartial(BaseModel):
    """Router streams response partial."""
    type: MessageType = MessageType.MODEL_PARTIAL
    session_id: str
    trace_id: str
    content: str  # Chunk of streaming response
    index: int  # Sequence number for ordering
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelFinal(BaseModel):
    """Router sends final response."""
    type: MessageType = MessageType.MODEL_FINAL
    session_id: str
    trace_id: str
    content: str  # Complete response
    actions: Optional[List[Dict[str, Any]]] = None  # Embedded actions if any
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelInvokeAction(BaseModel):
    """Router sends action to execute (embedded in response)."""
    type: MessageType = MessageType.MODEL_INVOKE_ACTION
    session_id: str
    trace_id: str
    action_id: str
    action_type: str  # 'booking.reserve', 'payment.process', etc.
    parameters: Dict[str, Any]
    requires_confirmation: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionResult(BaseModel):
    """Router confirms action execution (via passthrough)."""
    type: MessageType = MessageType.ACTION_RESULT
    session_id: str
    trace_id: str
    action_id: str
    action_type: str
    status: str  # 'completed', 'pending_confirmation', 'error'
    result: Any
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionDeferred(BaseModel):
    """Action confirmation timed out or moved to tray."""
    type: MessageType = MessageType.ACTION_DEFERRED
    session_id: str
    action_id: str
    action_type: str
    status: str  # 'pending_user' | 'expired'
    reason: Optional[str] = None
    expires_at: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SagaUpdate(BaseModel):
    """Saga state update for clients."""
    type: MessageType = MessageType.SAGA_UPDATE
    session_id: str
    saga_id: str
    saga_type: Optional[str] = None
    state: str
    steps: Optional[List[Dict[str, Any]]] = None
    result: Optional[Any] = None
    updated_at: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionConnected(BaseModel):
    """Gateway confirms WebSocket connection established."""
    type: MessageType = MessageType.SESSION_CONNECTED
    session_id: str
    user_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionReconnected(BaseModel):
    """Gateway confirms session resumed after reconnect."""
    type: MessageType = MessageType.SESSION_RECONNECTED
    session_id: str
    user_id: str
    pending_messages: List[Dict[str, Any]] = Field(default_factory=list)  # Queued messages during disconnect
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionError(BaseModel):
    """Gateway notifies client of session error."""
    type: MessageType = MessageType.SESSION_ERROR
    session_id: str
    error: str
    recoverable: bool = False  # Can client reconnect?
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Union type for all possible messages
WebSocketMessage = (
    ClientMessage
    | ModelPartial
    | ModelFinal
    | ModelInvokeAction
    | ActionResult
    | ActionDeferred
    | SagaUpdate
    | SessionConnected
    | SessionReconnected
    | SessionError
)
