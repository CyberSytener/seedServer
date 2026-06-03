"""Async session store for agent sessions (Phase 7 — P7-02).

Uses ``AsyncSqliteDB`` (``run_in_executor``) to avoid blocking the event loop.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    ParticipantRole,
    SessionParticipant,
    SessionStatus,
)
from app.infrastructure.db.async_sqlite import AsyncSqliteDB


class AgentSessionStore:
    """CRUD + message append + history query for agent sessions.

    All public methods are ``async`` — they delegate to the synchronous SQLite
    layer via ``AsyncSqliteDB.run_in_executor`` so the event loop is never
    blocked on I/O.
    """

    def __init__(self, db: AsyncSqliteDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    async def create_session(self, session: AgentSessionData) -> AgentSessionData:
        await self._db.execute(
            "INSERT INTO agent_sessions "
            "(session_id, user_id, persona_id, persona_overrides, budget_config, "
            "tool_scopes, pending_confirmations, status, created_at, updated_at, "
            "parent_session_id, tenant_id, project_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            session.to_row(),
        )
        return session

    async def get_session(self, session_id: str) -> Optional[AgentSessionData]:
        row = await self._db.fetchone(
            "SELECT * FROM agent_sessions WHERE session_id = ?",
            (session_id,),
        )
        if row is None:
            return None
        return AgentSessionData.from_row(row)

    async def update_session(self, session: AgentSessionData) -> None:
        session.updated_at = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE agent_sessions SET "
            "persona_id = ?, persona_overrides = ?, budget_config = ?, "
            "tool_scopes = ?, pending_confirmations = ?, status = ?, updated_at = ? "
            "WHERE session_id = ?",
            (
                session.persona_id,
                json.dumps(session.persona_overrides),
                json.dumps(session.budget_config),
                json.dumps(session.tool_scopes),
                json.dumps(session.pending_confirmations),
                session.status.value if isinstance(session.status, SessionStatus) else session.status,
                session.updated_at,
                session.session_id,
            ),
        )

    async def delete_session(self, session_id: str) -> None:
        await self._db.execute(
            "DELETE FROM agent_sessions WHERE session_id = ?",
            (session_id,),
        )

    async def list_sessions_for_user(
        self, user_id: str, *, status: Optional[str] = None, limit: int = 50
    ) -> List[AgentSessionData]:
        if status:
            rows = await self._db.fetchall(
                "SELECT * FROM agent_sessions WHERE user_id = ? AND status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, status, limit),
            )
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM agent_sessions WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        return [AgentSessionData.from_row(r) for r in rows]

    async def list_child_sessions(
        self, parent_session_id: str
    ) -> List[AgentSessionData]:
        """Return all direct child sessions of a given parent."""
        rows = await self._db.fetchall(
            "SELECT * FROM agent_sessions WHERE parent_session_id = ? "
            "ORDER BY created_at ASC",
            (parent_session_id,),
        )
        return [AgentSessionData.from_row(r) for r in rows]

    async def get_session_tree(
        self, root_session_id: str
    ) -> List[AgentSessionData]:
        """Return the full session tree rooted at *root_session_id*.

        Performs iterative breadth-first traversal; returns root + all
        descendants in BFS order.
        """
        root = await self.get_session(root_session_id)
        if root is None:
            return []
        tree: List[AgentSessionData] = [root]
        queue = [root_session_id]
        while queue:
            parent_id = queue.pop(0)
            children = await self.list_child_sessions(parent_id)
            for child in children:
                tree.append(child)
                queue.append(child.session_id)
        return tree

    async def cancel_session_tree(
        self, root_session_id: str
    ) -> List[str]:
        """Cancel *root_session_id* and all descendants.

        Returns the list of cancelled session_ids.
        """
        tree = await self.get_session_tree(root_session_id)
        cancelled: List[str] = []
        for session in tree:
            if session.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
                session.status = SessionStatus.COMPLETED
                await self.update_session(session)
                cancelled.append(session.session_id)
        return cancelled

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def append_message(self, message: AgentSessionMessage) -> None:
        await self._db.execute(
            "INSERT INTO agent_session_messages "
            "(message_id, session_id, role, content, tool_name, tool_input, "
            "tool_output, budget_snapshot, timestamp, sender_user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            message.to_row(),
        )

    async def get_messages(
        self, session_id: str, *, limit: int = 200
    ) -> List[AgentSessionMessage]:
        rows = await self._db.fetchall(
            "SELECT * FROM agent_session_messages WHERE session_id = ? "
            "ORDER BY timestamp ASC LIMIT ?",
            (session_id, limit),
        )
        return [AgentSessionMessage.from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Participants (P0-24)
    # ------------------------------------------------------------------

    async def add_participant(self, participant: SessionParticipant) -> None:
        """Insert or replace a participant row (idempotent upsert)."""
        await self._db.execute(
            "INSERT OR REPLACE INTO agent_session_participants "
            "(session_id, user_id, role, tool_scopes, joined_at, left_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            participant.to_row(),
        )

    async def remove_participant(self, session_id: str, user_id: str) -> bool:
        """Soft-remove by setting left_at. Returns False if participant is owner."""
        row = await self._db.fetchone(
            "SELECT role FROM agent_session_participants "
            "WHERE session_id = ? AND user_id = ? AND left_at IS NULL",
            (session_id, user_id),
        )
        if row is None:
            return False
        role = row[0] if not hasattr(row, "keys") else row["role"]
        if role == ParticipantRole.OWNER.value or role == ParticipantRole.OWNER:
            return False  # owner cannot be removed
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE agent_session_participants SET left_at = ? "
            "WHERE session_id = ? AND user_id = ?",
            (now, session_id, user_id),
        )
        return True

    async def get_participant(
        self, session_id: str, user_id: str
    ) -> Optional[SessionParticipant]:
        row = await self._db.fetchone(
            "SELECT * FROM agent_session_participants "
            "WHERE session_id = ? AND user_id = ? AND left_at IS NULL",
            (session_id, user_id),
        )
        if row is None:
            return None
        return SessionParticipant.from_row(row)

    async def list_participants(
        self, session_id: str, *, include_left: bool = False
    ) -> List[SessionParticipant]:
        if include_left:
            rows = await self._db.fetchall(
                "SELECT * FROM agent_session_participants WHERE session_id = ? "
                "ORDER BY joined_at ASC",
                (session_id,),
            )
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM agent_session_participants WHERE session_id = ? "
                "AND left_at IS NULL ORDER BY joined_at ASC",
                (session_id,),
            )
        return [SessionParticipant.from_row(r) for r in rows]
