"""Agent session data models (Phase 7 — P7-02 / P7-05).

All models are plain dataclasses and JSON-serializable for SQLite persistence.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Agent response (P7-05)
# ---------------------------------------------------------------------------

@dataclass
class AgentResponse:
    """Return value from ``AgentSession.process_message()``."""

    text: str = ""
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    budget_snapshot: Dict[str, Any] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    pending_confirmations: List[Dict[str, Any]] = field(default_factory=list)
    stopped_reason: Optional[str] = None
    persona_meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "artifacts": self.artifacts,
            "budget_snapshot": self.budget_snapshot,
            "trace": self.trace,
            "pending_confirmations": self.pending_confirmations,
            "stopped_reason": self.stopped_reason,
            "persona_meta": self.persona_meta,
        }


# ---------------------------------------------------------------------------
# Telemetry models (P7-07)
# ---------------------------------------------------------------------------

@dataclass
class AgentTraceStep:
    """Single step within an agent trace."""

    step_index: int = 0
    step_type: str = ""           # llm_call | tool_executed | tool_denied | confirmation_required | confirmation_cancelled
    tool_name: Optional[str] = None
    tool_input_hash: Optional[str] = None
    tool_output_hash: Optional[str] = None
    duration_ms: float = 0.0
    budget_snapshot: Dict[str, Any] = field(default_factory=dict)
    scope_check_result: Optional[str] = None  # "allowed" | "denied" | None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "step_type": self.step_type,
            "tool_name": self.tool_name,
            "tool_input_hash": self.tool_input_hash,
            "tool_output_hash": self.tool_output_hash,
            "duration_ms": self.duration_ms,
            "budget_snapshot": self.budget_snapshot,
            "scope_check_result": self.scope_check_result,
            "extra": self.extra,
        }


@dataclass
class AgentTrace:
    """Full trace for a ``process_message()`` call."""

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    user_id: str = ""
    # P0-20: link traces across parent/child sessions
    parent_session_id: Optional[str] = None
    parent_trace_id: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: Optional[str] = None
    steps: List[AgentTraceStep] = field(default_factory=list)
    budget_snapshot: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, **kwargs) -> AgentTraceStep:
        step = AgentTraceStep(step_index=len(self.steps), **kwargs)
        self.steps.append(step)
        return step

    def finalize(self, budget_snapshot: Dict[str, Any]) -> None:
        self.ended_at = datetime.now(timezone.utc).isoformat()
        self.budget_snapshot = budget_snapshot

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "parent_session_id": self.parent_session_id,
            "parent_trace_id": self.parent_trace_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "steps": [s.to_dict() for s in self.steps],
            "budget_snapshot": self.budget_snapshot,
        }


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"


class MessageRole(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    CONTEXT = "context"
    CONFIRMATION_REQUEST = "confirmation_request"


class ParticipantRole(str, Enum):
    """Role within a multi-user agent session (P0-24)."""
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


# ---------------------------------------------------------------------------
# Session participant (P0-24)
# ---------------------------------------------------------------------------

@dataclass
class SessionParticipant:
    """A user's participation record in an agent session."""

    session_id: str = ""
    user_id: str = ""
    role: ParticipantRole = ParticipantRole.VIEWER
    tool_scopes: List[str] = field(default_factory=list)
    joined_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    left_at: Optional[str] = None

    def to_row(self) -> tuple:
        return (
            self.session_id,
            self.user_id,
            self.role.value if isinstance(self.role, ParticipantRole) else self.role,
            json.dumps(self.tool_scopes),
            self.joined_at,
            self.left_at,
        )

    @classmethod
    def from_row(cls, row: Any) -> "SessionParticipant":
        if hasattr(row, "keys"):
            return cls(
                session_id=row["session_id"],
                user_id=row["user_id"],
                role=ParticipantRole(row["role"]),
                tool_scopes=json.loads(row["tool_scopes"] or "[]"),
                joined_at=row["joined_at"],
                left_at=row["left_at"],
            )
        return cls(
            session_id=row[0],
            user_id=row[1],
            role=ParticipantRole(row[2]),
            tool_scopes=json.loads(row[3] or "[]"),
            joined_at=row[4],
            left_at=row[5] if len(row) > 5 else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "role": self.role.value if isinstance(self.role, ParticipantRole) else self.role,
            "tool_scopes": self.tool_scopes,
            "joined_at": self.joined_at,
            "left_at": self.left_at,
        }


# ---------------------------------------------------------------------------
# Pending confirmation
# ---------------------------------------------------------------------------

@dataclass
class PendingConfirmation:
    """A tool call that requires user confirmation before execution."""

    confirmation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "explanation": self.explanation,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PendingConfirmation":
        return cls(
            confirmation_id=d.get("confirmation_id", str(uuid.uuid4())),
            tool_name=d.get("tool_name", ""),
            tool_input=d.get("tool_input", {}),
            explanation=d.get("explanation", ""),
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


# ---------------------------------------------------------------------------
# Persona overrides (P7-10)
# ---------------------------------------------------------------------------

MAX_SYSTEM_PROMPT_APPEND_CHARS = 2000

@dataclass
class PersonaOverrides:
    """Per-session persona overlays.

    - ``display_name``: client-visible alias (e.g. "Nikita")
    - ``voice_id``: opaque client-side voice identifier
    - ``system_prompt_append``: appended to base persona prompt (max 2000 chars)
    """

    display_name: Optional[str] = None
    voice_id: Optional[str] = None
    system_prompt_append: Optional[str] = None

    def __post_init__(self):
        if (
            self.system_prompt_append is not None
            and len(self.system_prompt_append) > MAX_SYSTEM_PROMPT_APPEND_CHARS
        ):
            raise ValueError(
                f"system_prompt_append exceeds max {MAX_SYSTEM_PROMPT_APPEND_CHARS} chars "
                f"(got {len(self.system_prompt_append)})"
            )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.display_name is not None:
            d["display_name"] = self.display_name
        if self.voice_id is not None:
            d["voice_id"] = self.voice_id
        if self.system_prompt_append is not None:
            d["system_prompt_append"] = self.system_prompt_append
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PersonaOverrides":
        return cls(
            display_name=d.get("display_name"),
            voice_id=d.get("voice_id"),
            system_prompt_append=d.get("system_prompt_append"),
        )


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AgentSessionData:
    """Persistent session state stored in ``agent_sessions`` table."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    persona_id: str = "seed"
    persona_overrides: Dict[str, Any] = field(default_factory=dict)
    budget_config: Dict[str, Any] = field(default_factory=dict)
    tool_scopes: List[str] = field(default_factory=list)
    pending_confirmations: List[Dict[str, Any]] = field(default_factory=list)
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # P0-20: parent link for sub-agent session spawning
    parent_session_id: Optional[str] = None
    # P0-36: tenant billing association
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_row(self) -> tuple:
        """Return a tuple suitable for SQL INSERT/REPLACE."""
        return (
            self.session_id,
            self.user_id,
            self.persona_id,
            json.dumps(self.persona_overrides),
            json.dumps(self.budget_config),
            json.dumps(self.tool_scopes),
            json.dumps(self.pending_confirmations),
            self.status.value if isinstance(self.status, SessionStatus) else self.status,
            self.created_at,
            self.updated_at,
            self.parent_session_id,
            self.tenant_id,
            self.project_id,
        )

    @classmethod
    def from_row(cls, row: Any) -> "AgentSessionData":
        """Construct from a sqlite3.Row or tuple."""
        if hasattr(row, "keys"):
            # sqlite3.Row
            return cls(
                session_id=row["session_id"],
                user_id=row["user_id"],
                persona_id=row["persona_id"],
                persona_overrides=json.loads(row["persona_overrides"] or "{}"),
                budget_config=json.loads(row["budget_config"] or "{}"),
                tool_scopes=json.loads(row["tool_scopes"] or "[]"),
                pending_confirmations=json.loads(row["pending_confirmations"] or "[]"),
                status=SessionStatus(row["status"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                parent_session_id=row["parent_session_id"],
                tenant_id=row["tenant_id"] if "tenant_id" in (row.keys() if callable(row.keys) else row.keys) else None,
                project_id=row["project_id"] if "project_id" in (row.keys() if callable(row.keys) else row.keys) else None,
            )
        # tuple/list fallback (positional)
        return cls(
            session_id=row[0],
            user_id=row[1],
            persona_id=row[2],
            persona_overrides=json.loads(row[3] or "{}"),
            budget_config=json.loads(row[4] or "{}"),
            tool_scopes=json.loads(row[5] or "[]"),
            pending_confirmations=json.loads(row[6] or "[]"),
            status=SessionStatus(row[7]),
            created_at=row[8],
            updated_at=row[9],
            parent_session_id=row[10] if len(row) > 10 else None,
            tenant_id=row[11] if len(row) > 11 else None,
            project_id=row[12] if len(row) > 12 else None,
        )


@dataclass
class AgentSessionMessage:
    """Single message in an agent session conversation."""

    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    role: MessageRole = MessageRole.USER
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None
    tool_output: Optional[str] = None
    budget_snapshot: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sender_user_id: Optional[str] = None

    def to_row(self) -> tuple:
        return (
            self.message_id,
            self.session_id,
            self.role.value if isinstance(self.role, MessageRole) else self.role,
            self.content,
            self.tool_name,
            self.tool_input,
            self.tool_output,
            self.budget_snapshot,
            self.timestamp,
            self.sender_user_id,
        )

    @classmethod
    def from_row(cls, row: Any) -> "AgentSessionMessage":
        if hasattr(row, "keys"):
            keys = row.keys() if callable(row.keys) else row.keys
            return cls(
                message_id=row["message_id"],
                session_id=row["session_id"],
                role=MessageRole(row["role"]),
                content=row["content"],
                tool_name=row["tool_name"],
                tool_input=row["tool_input"],
                tool_output=row["tool_output"],
                budget_snapshot=row["budget_snapshot"],
                timestamp=row["timestamp"],
                sender_user_id=row["sender_user_id"] if "sender_user_id" in keys else None,
            )
        return cls(
            message_id=row[0],
            session_id=row[1],
            role=MessageRole(row[2]),
            content=row[3],
            tool_name=row[4],
            tool_input=row[5],
            tool_output=row[6],
            budget_snapshot=row[7],
            timestamp=row[8],
            sender_user_id=row[9] if len(row) > 9 else None,
        )
