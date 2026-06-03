"""Agent session HTTP API endpoints (Phase 7 — P7-06).

Factory function ``build_agent_router()`` returns a FastAPI ``APIRouter``
with 6 endpoints for agent session management.

All endpoints are scope-protected via ``app.core.authz.require_scope()``.
Session isolation: users can only access their own sessions.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    ParticipantRole,
    SessionParticipant,
    SessionStatus,
)
from app.core.agent.session import AgentSession
from app.core.agent.session_store import AgentSessionStore
from app.core.agent.tool_registry import ToolRegistry
from app.core.agent.ui_context import UIContextPack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    persona_id: str = "seed"
    budget: Dict[str, Any] = Field(default_factory=dict)
    tool_scopes: List[str] = Field(default_factory=list)
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str
    persona_id: str
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None


class SendMessageRequest(BaseModel):
    message: str


class SendMessageResponse(BaseModel):
    text: str
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    budget_snapshot: Dict[str, Any] = Field(default_factory=dict)
    trace: List[Dict[str, Any]] = Field(default_factory=list)
    pending_confirmations: List[Dict[str, Any]] = Field(default_factory=list)
    stopped_reason: Optional[str] = None
    persona_meta: Dict[str, Any] = Field(default_factory=dict)


class SessionDetailResponse(BaseModel):
    session_id: str
    user_id: str
    persona_id: str
    status: str
    budget_config: Dict[str, Any] = Field(default_factory=dict)
    tool_scopes: List[str] = Field(default_factory=list)
    pending_confirmations: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    parent_session_id: Optional[str] = None
    children: List[Dict[str, Any]] = Field(default_factory=list)


class SessionTreeNodeResponse(BaseModel):
    session_id: str
    parent_session_id: Optional[str] = None
    user_id: str
    persona_id: str
    status: str
    budget_snapshot: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class SessionTreeResponse(BaseModel):
    root_session_id: str
    nodes: List[SessionTreeNodeResponse] = Field(default_factory=list)


class UpdatePersonaRequest(BaseModel):
    persona_id: Optional[str] = None
    name: Optional[str] = None
    voice: Optional[str] = None
    system_prompt: Optional[str] = None


class UpdatePersonaResponse(BaseModel):
    session_id: str
    persona_id: str
    persona_overrides: Dict[str, Any]


class ToolListResponse(BaseModel):
    tools: List[Dict[str, Any]]


class DeleteSessionResponse(BaseModel):
    session_id: str
    status: str
    cancelled_ids: List[str] = Field(default_factory=list)


class IngestContextResponse(BaseModel):
    session_id: str
    source: str
    components_count: int
    routes_count: int


class IngestRepoContextResponse(BaseModel):
    session_id: str
    repo_url: str
    files_count: int


class AddParticipantRequest(BaseModel):
    user_id: str
    role: str = "viewer"  # owner | editor | viewer
    tool_scopes: List[str] = Field(default_factory=list)


class ParticipantResponse(BaseModel):
    session_id: str
    user_id: str
    role: str
    tool_scopes: List[str] = Field(default_factory=list)
    joined_at: str
    left_at: Optional[str] = None


class ParticipantListResponse(BaseModel):
    session_id: str
    participants: List[ParticipantResponse] = Field(default_factory=list)


class RemoveParticipantResponse(BaseModel):
    session_id: str
    user_id: str
    removed: bool


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_agent_router(
    *,
    session_store: AgentSessionStore,
    tool_registry: ToolRegistry,
    action_router: Any,
    llm_service: Any,
    artifact_store: Any = None,
    persona_loader: Any = None,
    auth_provider: Any = None,
) -> APIRouter:
    """Build and return FastAPI router for agent session endpoints.

    Parameters
    ----------
    auth_provider:
        Callable ``(request, scope) -> AuthContext`` for scope-based auth.
        If ``None``, attempts to use ``app.core.authz.require_scope``.
    """

    router = APIRouter(prefix="/v1/agent", tags=["Agent Sessions"])

    # ----- Auth helper -----

    def _require_auth(request: Request, scope: str):
        """Resolve auth context and enforce required scope."""
        if auth_provider is not None:
            return auth_provider(request, scope)
        # Fallback: import from authz at runtime
        from app.core.authz import require_scope
        db = request.app.state.seed.db
        return require_scope(request, db, scope)

    def _effective_user_id(ctx: Any) -> str:
        """Extract user_id from auth context."""
        return getattr(ctx, "user_id", None) or getattr(ctx, "subject", "unknown")

    def _ensure_owner(session: AgentSessionData, user_id: str):
        """Raise 403 if user doesn't own the session."""
        if session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Not your session")

    async def _ensure_participant(
        session: AgentSessionData, user_id: str
    ) -> Optional[SessionParticipant]:
        """Return participant record if user is owner or active participant.

        Raises 403 otherwise. Owner gets a synthetic OWNER participant.
        """
        if session.user_id == user_id:
            return SessionParticipant(
                session_id=session.session_id,
                user_id=user_id,
                role=ParticipantRole.OWNER,
                tool_scopes=session.tool_scopes,
                joined_at=session.created_at,
            )
        p = await session_store.get_participant(session.session_id, user_id)
        if p is None:
            raise HTTPException(status_code=403, detail="Not a participant")
        return p

    # ----- AgentSession factory -----

    def _make_agent_session(ctx: Any) -> AgentSession:
        return AgentSession(
            session_store=session_store,
            tool_registry=tool_registry,
            action_router=action_router,
            llm_service=llm_service,
            artifact_store=artifact_store,
            persona_loader=persona_loader,
            auth_context=ctx,
        )

    # ----- 1. Create session -----

    @router.post("/sessions", response_model=CreateSessionResponse)
    async def create_session(body: CreateSessionRequest, request: Request):
        ctx = _require_auth(request, "agent:sessions")
        user_id = _effective_user_id(ctx)

        session = AgentSessionData(
            user_id=user_id,
            persona_id=body.persona_id,
            budget_config=body.budget if body.budget else AgentBudget().to_config(),
            tool_scopes=body.tool_scopes,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
        )
        created = await session_store.create_session(session)
        return CreateSessionResponse(
            session_id=created.session_id,
            status=created.status.value,
            persona_id=created.persona_id,
            tenant_id=created.tenant_id,
            project_id=created.project_id,
        )

    # ----- 2. Send message -----

    @router.post(
        "/sessions/{session_id}/messages",
        response_model=SendMessageResponse,
    )
    async def send_message(session_id: str, body: SendMessageRequest, request: Request):
        ctx = _require_auth(request, "agent:sessions")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        participant = await _ensure_participant(session, user_id)
        if participant.role == ParticipantRole.VIEWER:
            raise HTTPException(status_code=403, detail="Viewers cannot send messages")

        agent = _make_agent_session(ctx)
        resp = await agent.process_message(session_id, body.message)
        return SendMessageResponse(
            text=resp.text,
            artifacts=resp.artifacts,
            budget_snapshot=resp.budget_snapshot,
            trace=resp.trace,
            pending_confirmations=resp.pending_confirmations,
            stopped_reason=resp.stopped_reason,
            persona_meta=resp.persona_meta,
        )

    # ----- 3. Get session details -----

    @router.get(
        "/sessions/{session_id}",
        response_model=SessionDetailResponse,
    )
    async def get_session(session_id: str, request: Request):
        ctx = _require_auth(request, "agent:sessions")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        await _ensure_participant(session, user_id)

        messages = await session_store.get_messages(session_id)
        children = await session_store.list_child_sessions(session_id)
        return SessionDetailResponse(
            session_id=session.session_id,
            user_id=session.user_id,
            persona_id=session.persona_id,
            status=session.status.value,
            budget_config=session.budget_config,
            tool_scopes=session.tool_scopes,
            pending_confirmations=session.pending_confirmations,
            created_at=session.created_at,
            updated_at=session.updated_at,
            parent_session_id=session.parent_session_id,
            children=[
                {
                    "session_id": c.session_id,
                    "status": c.status.value if hasattr(c.status, "value") else c.status,
                    "persona_id": c.persona_id,
                    "created_at": c.created_at,
                }
                for c in children
            ],
            messages=[
                {
                    "role": m.role.value,
                    "content": m.content,
                    "tool_name": m.tool_name,
                    "timestamp": m.timestamp,
                    "sender_user_id": m.sender_user_id,
                }
                for m in messages
            ],
        )

    # ----- 4. Update persona -----

    @router.post(
        "/sessions/{session_id}/persona",
        response_model=UpdatePersonaResponse,
    )
    async def update_persona(session_id: str, body: UpdatePersonaRequest, request: Request):
        ctx = _require_auth(request, "agent:persona:write")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        _ensure_owner(session, user_id)

        if body.persona_id:
            session.persona_id = body.persona_id
        overrides: Dict[str, Any] = dict(session.persona_overrides)
        if body.system_prompt is not None:
            overrides["system_prompt"] = body.system_prompt
        if body.name is not None:
            overrides["display_name"] = body.name
        if body.voice is not None:
            overrides["voice_id"] = body.voice
        session.persona_overrides = overrides
        await session_store.update_session(session)

        return UpdatePersonaResponse(
            session_id=session.session_id,
            persona_id=session.persona_id,
            persona_overrides=session.persona_overrides,
        )

    # ----- 5. Delete session -----

    @router.delete(
        "/sessions/{session_id}",
        response_model=DeleteSessionResponse,
    )
    async def delete_session(session_id: str, request: Request):
        ctx = _require_auth(request, "agent:sessions")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        _ensure_owner(session, user_id)

        cancelled_ids = await session_store.cancel_session_tree(session_id)

        return DeleteSessionResponse(
            session_id=session.session_id,
            status="completed",
            cancelled_ids=cancelled_ids,
        )

    # ----- 6. Session tree (P0-22) -----

    @router.get(
        "/sessions/{session_id}/tree",
        response_model=SessionTreeResponse,
    )
    async def get_session_tree(session_id: str, request: Request):
        ctx = _require_auth(request, "agent:sessions")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        await _ensure_participant(session, user_id)

        tree = await session_store.get_session_tree(session_id)
        nodes = [
            SessionTreeNodeResponse(
                session_id=s.session_id,
                parent_session_id=s.parent_session_id,
                user_id=s.user_id,
                persona_id=s.persona_id,
                status=s.status.value if hasattr(s.status, "value") else s.status,
                budget_snapshot=s.budget_config,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in tree
        ]
        return SessionTreeResponse(
            root_session_id=session_id,
            nodes=nodes,
        )

    # ----- 8. Participants (P0-24) -----

    @router.post(
        "/sessions/{session_id}/participants",
        response_model=ParticipantResponse,
    )
    async def add_participant(
        session_id: str, body: AddParticipantRequest, request: Request
    ):
        ctx = _require_auth(request, "agent:sessions")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        _ensure_owner(session, user_id)

        try:
            role = ParticipantRole(body.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")
        if role == ParticipantRole.OWNER:
            raise HTTPException(status_code=400, detail="Cannot add another owner")

        participant = SessionParticipant(
            session_id=session_id,
            user_id=body.user_id,
            role=role,
            tool_scopes=body.tool_scopes,
        )
        await session_store.add_participant(participant)

        return ParticipantResponse(
            session_id=participant.session_id,
            user_id=participant.user_id,
            role=participant.role.value,
            tool_scopes=participant.tool_scopes,
            joined_at=participant.joined_at,
            left_at=participant.left_at,
        )

    @router.delete(
        "/sessions/{session_id}/participants/{target_user_id}",
        response_model=RemoveParticipantResponse,
    )
    async def remove_participant(
        session_id: str, target_user_id: str, request: Request
    ):
        ctx = _require_auth(request, "agent:sessions")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        _ensure_owner(session, user_id)

        removed = await session_store.remove_participant(session_id, target_user_id)
        return RemoveParticipantResponse(
            session_id=session_id,
            user_id=target_user_id,
            removed=removed,
        )

    @router.get(
        "/sessions/{session_id}/participants",
        response_model=ParticipantListResponse,
    )
    async def list_participants(session_id: str, request: Request):
        ctx = _require_auth(request, "agent:sessions")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        await _ensure_participant(session, user_id)

        parts = await session_store.list_participants(session_id)
        return ParticipantListResponse(
            session_id=session_id,
            participants=[
                ParticipantResponse(
                    session_id=p.session_id,
                    user_id=p.user_id,
                    role=p.role.value if hasattr(p.role, "value") else p.role,
                    tool_scopes=p.tool_scopes,
                    joined_at=p.joined_at,
                    left_at=p.left_at,
                )
                for p in parts
            ],
        )

    # ----- 9. Ingest UI context -----

    @router.post(
        "/sessions/{session_id}/context",
        response_model=IngestContextResponse,
    )
    async def ingest_context(session_id: str, request: Request):
        ctx = _require_auth(request, "agent:context:read")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        _ensure_owner(session, user_id)

        # Parse + validate body via UIContextPack (Pydantic)
        try:
            body = await request.json()
            pack = UIContextPack(**body)
        except Exception as exc:
            raise HTTPException(status_code=413, detail=str(exc))

        # Persist as a 'context' role message
        msg = AgentSessionMessage(
            session_id=session_id,
            role=MessageRole.CONTEXT,
            content=pack.model_dump_json(),
        )
        await session_store.append_message(msg)

        return IngestContextResponse(
            session_id=session_id,
            source=pack.source,
            components_count=len(pack.components),
            routes_count=len(pack.routes),
        )

    # ----- 10. Ingest repo context (P0-30) -----

    @router.post(
        "/sessions/{session_id}/repo-context",
        response_model=IngestRepoContextResponse,
    )
    async def ingest_repo_context(session_id: str, request: Request):
        ctx = _require_auth(request, "agent:context:read")
        user_id = _effective_user_id(ctx)

        session = await session_store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        _ensure_owner(session, user_id)

        # Parse + validate body via RepoContextPack
        try:
            body = await request.json()
            from app.core.agent.repo_context import RepoContextPack
            rpack = RepoContextPack.from_dict(body)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Persist as a 'context' role message (subtype=repo via type field in JSON)
        import json as _json
        msg = AgentSessionMessage(
            session_id=session_id,
            role=MessageRole.CONTEXT,
            content=_json.dumps(rpack.to_dict()),
        )
        await session_store.append_message(msg)

        return IngestRepoContextResponse(
            session_id=session_id,
            repo_url=rpack.repo_url,
            files_count=len(rpack.files),
        )

    # ----- 7. List tools -----

    @router.get("/tools", response_model=ToolListResponse)
    async def list_tools(request: Request):
        ctx = _require_auth(request, "agent:tools:read")
        # Return all available tool manifests (no session-specific filtering)
        manifests = tool_registry.list_tools_for_llm(["*"])
        return ToolListResponse(tools=manifests)

    return router
