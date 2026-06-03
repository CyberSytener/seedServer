from __future__ import annotations

import asyncio
from typing import Any, Dict, Set

from fastapi import WebSocket


class OrderStreamHub:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(websocket)

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(user_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(user_id, None)

    async def publish(self, user_id: str, message: Dict[str, Any], *, timeout: float = 2.0) -> None:
        async with self._lock:
            targets = list(self._connections.get(user_id) or [])

        for websocket in targets:
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=timeout)
            except Exception:
                await self.disconnect(user_id, websocket)
