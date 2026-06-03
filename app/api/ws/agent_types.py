"""Agent WebSocket message types for real-time streaming (P0-32).

Extends the existing ``MessageType`` enum pattern with ``agent.*`` prefixed
types for agent session streaming over the shared WebSocket connection.

All types are JSON-serializable Pydantic models following the existing
``app.api.ws.types`` pattern. Each message carries ``agent_session_id`` and
``message_id`` for correlation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared IDE protocol fields
# ---------------------------------------------------------------------------


class FileReference(BaseModel):
    """A file-level reference for IDE navigation."""

    path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent message type enum
# ---------------------------------------------------------------------------


class AgentMessageType(str, Enum):
    """Message types for agent session streaming over WebSocket."""

    # Client → Server
    STREAM_START = "agent.stream_start"

    # Server → Client
    PARTIAL = "agent.partial"
    TOOL_CALL_START = "agent.tool_call_start"
    TOOL_CALL_RESULT = "agent.tool_call_result"
    CONFIRMATION_REQUEST = "agent.confirmation_request"
    BUDGET_UPDATE = "agent.budget_update"
    FINAL = "agent.final"
    ERROR = "agent.error"


# ---------------------------------------------------------------------------
# Client → Server
# ---------------------------------------------------------------------------


class AgentStreamStart(BaseModel):
    """Client requests binding of this WS connection to an agent session."""

    type: AgentMessageType = AgentMessageType.STREAM_START
    agent_session_id: str
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None  # IDE-assigned correlation ID
    request_id: Optional[str] = None  # IDE-assigned request ID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Server → Client
# ---------------------------------------------------------------------------


class AgentPartial(BaseModel):
    """Streaming LLM text chunk (incremental)."""

    type: AgentMessageType = AgentMessageType.PARTIAL
    agent_session_id: str
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    content: str  # Text chunk
    index: int  # Sequence number for ordering
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentToolCallStart(BaseModel):
    """Agent is about to call a tool."""

    type: AgentMessageType = AgentMessageType.TOOL_CALL_START
    agent_session_id: str
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    tool_name: str
    input_preview: Optional[Dict[str, Any]] = None  # Sanitized input summary
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentToolCallResult(BaseModel):
    """Tool call completed."""

    type: AgentMessageType = AgentMessageType.TOOL_CALL_RESULT
    agent_session_id: str
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    tool_name: str
    output_summary: Optional[str] = None  # Brief text summary of output
    duration_ms: Optional[float] = None
    status: str = "success"  # "success" | "error"
    file_references: List[FileReference] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentConfirmationRequest(BaseModel):
    """Tool requires user confirmation before execution."""

    type: AgentMessageType = AgentMessageType.CONFIRMATION_REQUEST
    agent_session_id: str
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    confirmation_id: str  # ID to reference when confirming/denying
    tool_name: str
    proposed_input: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None  # Human-readable explanation
    diff: Optional[str] = None  # Unified diff for apply_patch operations
    file_references: List[FileReference] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentBudgetUpdate(BaseModel):
    """Budget snapshot after each processing step."""

    type: AgentMessageType = AgentMessageType.BUDGET_UPDATE
    agent_session_id: str
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    budget_snapshot: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentFinal(BaseModel):
    """Complete agent response — end of processing."""

    type: AgentMessageType = AgentMessageType.FINAL
    agent_session_id: str
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    text: str = ""
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    trace: List[Dict[str, Any]] = Field(default_factory=list)
    budget_snapshot: Dict[str, Any] = Field(default_factory=dict)
    file_references: List[FileReference] = Field(default_factory=list)
    stopped_reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentError(BaseModel):
    """Error during agent processing."""

    type: AgentMessageType = AgentMessageType.ERROR
    agent_session_id: str
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    error: str
    recoverable: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Union type for all agent WS messages
# ---------------------------------------------------------------------------

AgentWebSocketMessage = (
    AgentStreamStart
    | AgentPartial
    | AgentToolCallStart
    | AgentToolCallResult
    | AgentConfirmationRequest
    | AgentBudgetUpdate
    | AgentFinal
    | AgentError
)

# Map of type string → model class (for deserialization)
AGENT_MESSAGE_TYPES: Dict[str, type] = {
    AgentMessageType.STREAM_START: AgentStreamStart,
    AgentMessageType.PARTIAL: AgentPartial,
    AgentMessageType.TOOL_CALL_START: AgentToolCallStart,
    AgentMessageType.TOOL_CALL_RESULT: AgentToolCallResult,
    AgentMessageType.CONFIRMATION_REQUEST: AgentConfirmationRequest,
    AgentMessageType.BUDGET_UPDATE: AgentBudgetUpdate,
    AgentMessageType.FINAL: AgentFinal,
    AgentMessageType.ERROR: AgentError,
}


def parse_agent_message(data: Dict[str, Any]) -> AgentWebSocketMessage:
    """Parse a raw JSON dict into the appropriate agent message type.

    Raises ``ValueError`` if the type is unknown.
    """
    msg_type = data.get("type")
    cls = AGENT_MESSAGE_TYPES.get(msg_type)  # type: ignore[arg-type]
    if cls is None:
        raise ValueError(f"Unknown agent message type: {msg_type!r}")
    return cls(**data)
