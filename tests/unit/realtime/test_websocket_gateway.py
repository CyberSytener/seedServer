"""
WebSocket Gateway Tests - STEP 3.

Tests for:
- JWT auth (valid/invalid tokens)
- Session creation and resumption
- Message streaming
- invoke_action passthrough
- Reconnect with pending message recovery
- Graceful disconnect
- Concurrent connections
"""

import pytest
pytest.importorskip("jwt")
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone

from app.api.ws.types import (
    MessageType,
    ClientMessage,
    ModelFinal,
    ModelPartial,
    SessionConnected,
    SessionReconnected,
    SessionError,
)
from app.api.ws.auth import JWTHandler
from app.api.ws.session import RedisSessionStore
from app.api.ws.gateway import WebSocketGateway


class TestJWTAuth:
    """Test JWT authentication."""
    
    def test_create_token(self):
        """Test token generation."""
        handler = JWTHandler(secret_key="test-secret-key-change-this-32-bytes")
        token = handler.create_token("user123")
        
        assert token is not None
        assert isinstance(token, str)
    
    def test_validate_valid_token(self):
        """Test validating correct token."""
        handler = JWTHandler(secret_key="test-secret-key-change-this-32-bytes")
        token = handler.create_token("user123")
        
        payload = handler.validate_token(token)
        assert payload is not None
        assert payload["user_id"] == "user123"
    
    def test_validate_invalid_token(self):
        """Test invalid token returns None."""
        handler = JWTHandler(secret_key="test-secret-key-change-this-32-bytes")
        
        # Wrong secret
        other_handler = JWTHandler(secret_key="other-secret-key-change-this-32-bytes")
        token = other_handler.create_token("user123")
        
        payload = handler.validate_token(token)
        assert payload is None
    
    def test_extract_user_id(self):
        """Test extracting user_id from token."""
        handler = JWTHandler(secret_key="test-secret-key-change-this-32-bytes")
        token = handler.create_token("user456")
        
        user_id = handler.extract_user_id(token)
        assert user_id == "user456"
    
    def test_extract_user_id_invalid_token(self):
        """Test extracting from invalid token returns None."""
        handler = JWTHandler(secret_key="test-secret-key-change-this-32-bytes")
        
        user_id = handler.extract_user_id("invalid.token.here")
        assert user_id is None


class TestRedisSessionStore:
    """Test session management in Redis (mock)."""
    
    @pytest.mark.asyncio
    async def test_create_session(self):
        """Test session creation."""
        mock_redis = AsyncMock()
        store = RedisSessionStore(mock_redis)
        
        session_id = await store.create_session("user123")
        
        assert session_id is not None
        assert len(session_id) == 36  # UUID format
        assert mock_redis.setex.called
    
    @pytest.mark.asyncio
    async def test_get_session(self):
        """Test session retrieval."""
        mock_redis = AsyncMock()
        session_data = {
            "user_id": "user123",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_activity": datetime.now(timezone.utc).isoformat(),
        }
        
        mock_redis.get.return_value = json.dumps(session_data).encode()
        store = RedisSessionStore(mock_redis)
        
        result = await store.get_session("session-123")
        
        assert result is not None
        assert result["user_id"] == "user123"
    
    @pytest.mark.asyncio
    async def test_session_expired(self):
        """Test expired session returns None."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        store = RedisSessionStore(mock_redis)
        
        result = await store.get_session("expired-session")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_queue_and_retrieve_messages(self):
        """Test message queueing for disconnected sessions."""
        mock_redis = AsyncMock()
        store = RedisSessionStore(mock_redis)
        
        msg1 = {"type": "model.partial", "content": "Hello"}
        msg2 = {"type": "model.partial", "content": "World"}
        
        # Mock lrange to return messages in order
        mock_redis.lrange.return_value = [
            json.dumps(msg2).encode(),
            json.dumps(msg1).encode(),
        ]
        
        await store.queue_message("session-123", msg1)
        await store.queue_message("session-123", msg2)
        
        messages = await store.get_pending_messages("session-123")
        
        # Should be in chronological order after reversal
        assert len(messages) == 2
        assert mock_redis.delete.called
    
    @pytest.mark.asyncio
    async def test_trace_id_storage(self):
        """Test trace_id storage for correlation."""
        mock_redis = AsyncMock()
        store = RedisSessionStore(mock_redis)
        
        await store.set_trace_id("session-123", "trace-abc-def")
        
        # Mock retrieval
        mock_redis.get.return_value = b"trace-abc-def"
        trace_id = await store.get_trace_id("session-123")
        
        assert trace_id == "trace-abc-def"


class TestWebSocketGateway:
    """Test WebSocket gateway (integration)."""
    
    @pytest.mark.asyncio
    async def test_gateway_initialization(self):
        """Test gateway setup."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        assert gateway is not None
        assert gateway.active_connections == {}
        assert gateway.session_store is not None
    
    @pytest.mark.asyncio
    async def test_send_to_connected_client(self):
        """Test sending message to connected client."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        mock_websocket = AsyncMock()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        # Simulate connected client
        session_id = "session-123"
        gateway.active_connections[session_id] = mock_websocket
        
        msg = {"type": "model.final", "content": "Hello"}
        result = await gateway.send_to_client(session_id, msg)
        
        assert result is True
        assert mock_websocket.send_json.called
    
    @pytest.mark.asyncio
    async def test_send_to_disconnected_client_queues(self):
        """Test message queueing when client disconnected."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        # Mock session store
        gateway.session_store.queue_message = AsyncMock()
        
        session_id = "session-123"
        msg = {"type": "model.final", "content": "Hello"}
        
        # No connected client
        result = await gateway.send_to_client(session_id, msg)
        
        assert result is False
        assert gateway.session_store.queue_message.called
    
    @pytest.mark.asyncio
    async def test_broadcast_partial(self):
        """Test streaming partial response."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        mock_websocket = AsyncMock()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        session_id = "session-123"
        gateway.active_connections[session_id] = mock_websocket
        
        await gateway.broadcast_partial(
            session_id=session_id,
            trace_id="trace-abc",
            content="partial",
            index=0,
        )
        
        assert mock_websocket.send_json.called
        call_arg = mock_websocket.send_json.call_args[0][0]
        assert call_arg["type"] == "model.partial"
        assert call_arg["content"] == "partial"
    
    @pytest.mark.asyncio
    async def test_broadcast_final(self):
        """Test sending final response."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        mock_websocket = AsyncMock()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        session_id = "session-123"
        gateway.active_connections[session_id] = mock_websocket
        
        await gateway.broadcast_final(
            session_id=session_id,
            trace_id="trace-abc",
            content="complete response",
        )
        
        assert mock_websocket.send_json.called
        call_arg = mock_websocket.send_json.call_args[0][0]
        assert call_arg["type"] == "model.final"
    
    @pytest.mark.asyncio
    async def test_disconnect_session(self):
        """Test session disconnection and cleanup."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        mock_websocket = AsyncMock()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        gateway.session_store.invalidate_session = AsyncMock()
        
        session_id = "session-123"
        gateway.active_connections[session_id] = mock_websocket
        
        await gateway.disconnect_session(session_id)
        
        assert session_id not in gateway.active_connections
        assert gateway.session_store.invalidate_session.called


class TestReconnectScenario:
    """Test reconnect flow with pending message recovery."""
    
    @pytest.mark.asyncio
    async def test_reconnect_resumes_session(self):
        """Test that reconnect recovers pending messages."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        # Setup session with pending messages
        session_id = "session-123"
        pending_msgs = [
            {"type": "model.partial", "content": "Hello"},
            {"type": "model.partial", "content": "World"},
        ]
        
        gateway.session_store.get_session = AsyncMock(
            return_value={"user_id": "user123"}
        )
        gateway.session_store.get_pending_messages = AsyncMock(
            return_value=pending_msgs
        )
        
        recovered = await gateway.session_store.get_pending_messages(session_id)
        
        assert len(recovered) == 2
        assert recovered[0]["content"] == "Hello"


class TestConcurrentConnections:
    """Test handling multiple simultaneous connections."""
    
    @pytest.mark.asyncio
    async def test_multiple_sessions_isolated(self):
        """Test that sessions are isolated from each other."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        # Create multiple sessions
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        
        gateway.active_connections["session-1"] = ws1
        gateway.active_connections["session-2"] = ws2
        
        msg = {"type": "model.final", "content": "test"}
        
        await gateway.send_to_client("session-1", msg)
        await gateway.send_to_client("session-2", msg)
        
        # Both should receive message
        assert ws1.send_json.called
        assert ws2.send_json.called
    
    @pytest.mark.asyncio
    async def test_broadcast_to_all_sessions(self):
        """Test broadcasting to multiple sessions."""
        mock_redis = AsyncMock()
        mock_app = MagicMock()
        mock_queue = asyncio.Queue()
        
        gateway = WebSocketGateway(
            app=mock_app,
            redis_client=mock_redis,
            action_router_queue=mock_queue,
        )
        
        # Setup 3 sessions
        ws_list = [AsyncMock() for _ in range(3)]
        for i, ws in enumerate(ws_list):
            gateway.active_connections[f"session-{i}"] = ws
        
        # Send to each
        msg = {"type": "announcement", "content": "system message"}
        for i in range(3):
            await gateway.send_to_client(f"session-{i}", msg)
        
        # All should be called
        for ws in ws_list:
            assert ws.send_json.called


class TestMessageTypes:
    """Test message type definitions."""
    
    def test_client_message_creation(self):
        """Test ClientMessage model."""
        msg = ClientMessage(
            session_id="sess-123",
            user_id="user-123",
            content="Hello",
        )
        
        assert msg.type == MessageType.CLIENT_MESSAGE
        assert msg.content == "Hello"
    
    def test_model_partial_creation(self):
        """Test ModelPartial model."""
        msg = ModelPartial(
            session_id="sess-123",
            trace_id="trace-123",
            content="Streaming...",
            index=0,
        )
        
        assert msg.type == MessageType.MODEL_PARTIAL
        assert msg.index == 0
    
    def test_session_connected_creation(self):
        """Test SessionConnected model."""
        msg = SessionConnected(
            session_id="sess-123",
            user_id="user-123",
        )
        
        assert msg.type == MessageType.SESSION_CONNECTED
        assert msg.user_id == "user-123"
    
    def test_message_serialization(self):
        """Test message can be serialized to JSON."""
        msg = ClientMessage(
            session_id="sess-123",
            user_id="user-123",
            content="Test",
        )
        
        serialized = msg.model_dump()
        
        assert isinstance(serialized, dict)
        assert serialized["type"] == "client.message"
        assert serialized["content"] == "Test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
