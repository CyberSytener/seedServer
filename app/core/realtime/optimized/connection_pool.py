"""
WebSocket Connection Pool Manager

Manages multiple WebSocket connections with:
- Connection pooling and reuse
- Automatic reconnection
- Load balancing across connections
- Message routing by user_id/saga_id
- Health monitoring
"""

import asyncio
import time
import logging
from typing import Dict, Any, Optional, Set, Callable, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from collections import defaultdict
import uuid

logger = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    """WebSocket connection state."""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class ConnectionMetrics:
    """Metrics for a WebSocket connection."""
    connection_id: str
    user_id: str
    
    # Timing
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    
    # Counters
    messages_sent: int = 0
    messages_received: int = 0
    errors: int = 0
    
    # Performance
    avg_latency_ms: float = 0.0
    last_ping_ms: float = 0.0
    
    def age_seconds(self) -> float:
        """Connection age in seconds."""
        return time.time() - self.connected_at
    
    def idle_seconds(self) -> float:
        """Time since last activity."""
        return time.time() - self.last_activity
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "connection_id": self.connection_id,
            "user_id": self.user_id,
            "age_seconds": self.age_seconds(),
            "idle_seconds": self.idle_seconds(),
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "errors": self.errors,
            "avg_latency_ms": self.avg_latency_ms,
            "last_ping_ms": self.last_ping_ms,
        }


class WebSocketConnection:
    """Wrapper for WebSocket connection with metrics."""
    
    def __init__(self, websocket: Any, user_id: str, connection_id: Optional[str] = None):
        self.websocket = websocket
        self.connection_id = connection_id or str(uuid.uuid4())
        self.user_id = user_id
        self.state = ConnectionState.CONNECTED
        self.metrics = ConnectionMetrics(
            connection_id=self.connection_id,
            user_id=user_id,
        )
        
        # Active sagas for this connection
        self.active_sagas: Set[str] = set()
        
        # Ping/pong
        self.last_ping: float = 0
        self.last_pong: float = 0
    
    async def send(self, message: Dict[str, Any]):
        """Send message to client."""
        try:
            await self.websocket.send_json(message)
            self.metrics.messages_sent += 1
            self.metrics.last_activity = time.time()
        except Exception as e:
            logger.error(f"Error sending message on {self.connection_id}: {e}")
            self.metrics.errors += 1
            self.state = ConnectionState.ERROR
            raise
    
    async def receive(self) -> Dict[str, Any]:
        """Receive message from client."""
        try:
            message = await self.websocket.receive_json()
            self.metrics.messages_received += 1
            self.metrics.last_activity = time.time()
            return message
        except Exception as e:
            logger.error(f"Error receiving message on {self.connection_id}: {e}")
            self.metrics.errors += 1
            self.state = ConnectionState.ERROR
            raise
    
    async def ping(self) -> bool:
        """Send ping and measure latency."""
        try:
            self.last_ping = time.time()
            
            # Send ping message
            await self.send({"type": "ping", "timestamp": self.last_ping})
            
            # Wait for pong (with timeout)
            try:
                response = await asyncio.wait_for(self.receive(), timeout=5.0)
                
                if response.get("type") == "pong":
                    self.last_pong = time.time()
                    latency = (self.last_pong - self.last_ping) * 1000
                    self.metrics.last_ping_ms = latency
                    
                    # Update rolling average
                    if self.metrics.avg_latency_ms == 0:
                        self.metrics.avg_latency_ms = latency
                    else:
                        self.metrics.avg_latency_ms = (
                            self.metrics.avg_latency_ms * 0.9 + latency * 0.1
                        )
                    
                    return True
            except asyncio.TimeoutError:
                logger.warning(f"Ping timeout on {self.connection_id}")
                return False
        
        except Exception as e:
            logger.error(f"Ping error on {self.connection_id}: {e}")
            return False
        
        return False
    
    async def close(self):
        """Close connection."""
        try:
            self.state = ConnectionState.DISCONNECTING
            await self.websocket.close()
            self.state = ConnectionState.DISCONNECTED
        except Exception as e:
            logger.error(f"Error closing connection {self.connection_id}: {e}")
            self.state = ConnectionState.ERROR
    
    def is_healthy(self) -> bool:
        """Check if connection is healthy."""
        # Check state
        if self.state not in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
            return False
        
        # Check idle time (disconnect if idle > 5 minutes)
        if self.metrics.idle_seconds() > 300:
            return False
        
        # Check error rate
        total_messages = self.metrics.messages_sent + self.metrics.messages_received
        if total_messages > 10:
            error_rate = self.metrics.errors / total_messages
            if error_rate > 0.1:  # More than 10% errors
                return False
        
        return True


class ConnectionPool:
    """
    Manages multiple WebSocket connections.
    
    Features:
    - One connection per user
    - Automatic reconnection
    - Load balancing for broadcasts
    - Health monitoring
    """
    
    def __init__(
        self,
        max_connections: int = 1000,
        ping_interval: int = 30,
        cleanup_interval: int = 60,
    ):
        """
        Initialize connection pool.
        
        Args:
            max_connections: Maximum concurrent connections
            ping_interval: Seconds between ping checks
            cleanup_interval: Seconds between cleanup runs
        """
        self.max_connections = max_connections
        self.ping_interval = ping_interval
        self.cleanup_interval = cleanup_interval
        
        # Connections by user_id
        self.connections: Dict[str, WebSocketConnection] = {}
        
        # Connections by connection_id (for reverse lookup)
        self.conn_by_id: Dict[str, WebSocketConnection] = {}
        
        # Saga to connections mapping
        self.saga_connections: Dict[str, Set[str]] = defaultdict(set)
        
        # Background tasks
        self.ping_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        self.running = False
        
        # Metrics
        self.total_connected = 0
        self.total_disconnected = 0
        self.total_errors = 0
    
    async def start(self):
        """Start background tasks."""
        if self.running:
            return
        
        self.running = True
        
        # Start ping task
        self.ping_task = asyncio.create_task(self._ping_loop())
        
        # Start cleanup task
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info("✅ Connection pool started")
    
    async def stop(self):
        """Stop background tasks."""
        self.running = False
        
        # Cancel tasks
        if self.ping_task:
            self.ping_task.cancel()
        if self.cleanup_task:
            self.cleanup_task.cancel()
        
        # Close all connections
        for conn in list(self.connections.values()):
            await conn.close()
        
        self.connections.clear()
        self.conn_by_id.clear()
        self.saga_connections.clear()
        
        logger.info("🛑 Connection pool stopped")
    
    async def add_connection(
        self,
        websocket: Any,
        user_id: str,
        connection_id: Optional[str] = None,
    ) -> WebSocketConnection:
        """
        Add new connection to pool.
        
        Args:
            websocket: WebSocket instance
            user_id: User ID
            connection_id: Optional connection ID
            
        Returns:
            WebSocketConnection
        """
        # Check if at capacity
        if len(self.connections) >= self.max_connections:
            # Remove oldest idle connection
            await self._evict_oldest_idle()
        
        # Remove existing connection for this user
        if user_id in self.connections:
            old_conn = self.connections[user_id]
            logger.info(f"Replacing existing connection for user {user_id}")
            await self.remove_connection(user_id)
        
        # Create new connection
        conn = WebSocketConnection(websocket, user_id, connection_id)
        
        # Store
        self.connections[user_id] = conn
        self.conn_by_id[conn.connection_id] = conn
        
        self.total_connected += 1
        
        logger.info(
            f"✅ Connection added: {conn.connection_id} | "
            f"User: {user_id} | "
            f"Total: {len(self.connections)}"
        )
        
        return conn
    
    async def remove_connection(self, user_id: str):
        """Remove connection from pool."""
        if user_id not in self.connections:
            return
        
        conn = self.connections[user_id]
        
        # Close connection
        await conn.close()
        
        # Remove from mappings
        del self.connections[user_id]
        del self.conn_by_id[conn.connection_id]
        
        # Remove from saga mappings
        for saga_id in conn.active_sagas:
            self.saga_connections[saga_id].discard(conn.connection_id)
        
        self.total_disconnected += 1
        
        logger.info(f"🔌 Connection removed: {conn.connection_id} | User: {user_id}")
    
    def get_connection(self, user_id: str) -> Optional[WebSocketConnection]:
        """Get connection by user ID."""
        return self.connections.get(user_id)
    
    def get_connection_by_id(self, connection_id: str) -> Optional[WebSocketConnection]:
        """Get connection by connection ID."""
        return self.conn_by_id.get(connection_id)
    
    async def send_to_user(self, user_id: str, message: Dict[str, Any]) -> bool:
        """Send message to specific user."""
        conn = self.get_connection(user_id)
        if not conn:
            logger.warning(f"No connection for user {user_id}")
            return False
        
        try:
            await conn.send(message)
            return True
        except Exception as e:
            logger.error(f"Failed to send to user {user_id}: {e}")
            # Remove bad connection
            await self.remove_connection(user_id)
            return False
    
    async def broadcast_to_saga(self, saga_id: str, message: Dict[str, Any]):
        """Broadcast message to all connections involved in a saga."""
        connection_ids = self.saga_connections.get(saga_id, set())
        
        if not connection_ids:
            logger.debug(f"No connections for saga {saga_id}")
            return
        
        # Send to all connections
        tasks = []
        for conn_id in connection_ids:
            conn = self.get_connection_by_id(conn_id)
            if conn:
                tasks.append(conn.send(message))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log errors
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Broadcast error: {result}")
    
    async def broadcast_to_all(self, message: Dict[str, Any]):
        """Broadcast message to all connections."""
        if not self.connections:
            return
        
        tasks = [conn.send(message) for conn in self.connections.values()]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successes/failures
        success = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - success
        
        logger.info(f"📢 Broadcast: {success} succeeded, {failed} failed")
    
    def register_saga(self, saga_id: str, user_id: str):
        """Register a saga for a user connection."""
        conn = self.get_connection(user_id)
        if conn:
            conn.active_sagas.add(saga_id)
            self.saga_connections[saga_id].add(conn.connection_id)
            logger.debug(f"Registered saga {saga_id} for user {user_id}")
    
    def unregister_saga(self, saga_id: str, user_id: Optional[str] = None):
        """Unregister a saga."""
        if user_id:
            conn = self.get_connection(user_id)
            if conn:
                conn.active_sagas.discard(saga_id)
        
        # Remove from saga_connections
        if saga_id in self.saga_connections:
            del self.saga_connections[saga_id]
    
    async def _ping_loop(self):
        """Background task to ping all connections."""
        while self.running:
            try:
                await asyncio.sleep(self.ping_interval)
                
                if not self.connections:
                    continue
                
                logger.debug(f"Pinging {len(self.connections)} connections...")
                
                # Ping all connections
                tasks = [conn.ping() for conn in self.connections.values()]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Remove dead connections
                dead_users = []
                for conn, result in zip(self.connections.values(), results):
                    if isinstance(result, Exception) or not result:
                        dead_users.append(conn.user_id)
                
                for user_id in dead_users:
                    logger.warning(f"Removing dead connection for user {user_id}")
                    await self.remove_connection(user_id)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Ping loop error: {e}")
    
    async def _cleanup_loop(self):
        """Background task to cleanup unhealthy connections."""
        while self.running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                
                # Find unhealthy connections
                unhealthy = []
                for user_id, conn in self.connections.items():
                    if not conn.is_healthy():
                        unhealthy.append(user_id)
                
                # Remove unhealthy
                for user_id in unhealthy:
                    logger.warning(f"Removing unhealthy connection for user {user_id}")
                    await self.remove_connection(user_id)
                
                if unhealthy:
                    logger.info(f"Cleaned up {len(unhealthy)} unhealthy connections")
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Cleanup loop error: {e}")
    
    async def _evict_oldest_idle(self):
        """Evict oldest idle connection."""
        if not self.connections:
            return
        
        # Find oldest idle
        oldest_conn = max(
            self.connections.values(),
            key=lambda c: c.metrics.idle_seconds()
        )
        
        logger.warning(
            f"Evicting oldest idle connection: {oldest_conn.connection_id} | "
            f"Idle: {oldest_conn.metrics.idle_seconds():.1f}s"
        )
        
        await self.remove_connection(oldest_conn.user_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        # Connection stats
        healthy = sum(1 for c in self.connections.values() if c.is_healthy())
        
        # Message stats
        total_sent = sum(c.metrics.messages_sent for c in self.connections.values())
        total_received = sum(c.metrics.messages_received for c in self.connections.values())
        
        # Latency stats
        latencies = [c.metrics.avg_latency_ms for c in self.connections.values() if c.metrics.avg_latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        
        return {
            "connections": {
                "active": len(self.connections),
                "healthy": healthy,
                "max": self.max_connections,
                "utilization": f"{(len(self.connections) / self.max_connections * 100):.1f}%",
            },
            "lifetime": {
                "total_connected": self.total_connected,
                "total_disconnected": self.total_disconnected,
                "total_errors": self.total_errors,
            },
            "messages": {
                "sent": total_sent,
                "received": total_received,
                "total": total_sent + total_received,
            },
            "performance": {
                "avg_latency_ms": f"{avg_latency:.1f}",
            },
            "sagas": {
                "active": len(self.saga_connections),
            },
        }
    
    def get_connection_details(self) -> List[Dict[str, Any]]:
        """Get detailed info for all connections."""
        return [conn.metrics.to_dict() for conn in self.connections.values()]
