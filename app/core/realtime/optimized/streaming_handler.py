"""
Streaming AI Response Handler

Handles streaming responses from LLM with minimal latency:
- Server-Sent Events (SSE) streaming
- WebSocket streaming
- Chunk aggregation and buffering
- Progress updates during generation
- Cancellation support
"""

import asyncio
import time
import logging
from typing import Dict, Any, Optional, AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json

logger = logging.getLogger(__name__)


class StreamState(str, Enum):
    """Stream state."""
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class StreamChunk:
    """A chunk of streaming data."""
    stream_id: str
    sequence: int
    content: str
    metadata: Optional[Dict[str, Any]] = None
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        return {
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class StreamSession:
    """Manages a single streaming session."""
    
    def __init__(
        self,
        stream_id: str,
        user_id: str,
        request_params: Dict[str, Any],
    ):
        self.stream_id = stream_id
        self.user_id = user_id
        self.request_params = request_params
        
        # State
        self.state = StreamState.PENDING
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        
        # Content
        self.chunks: list[StreamChunk] = []
        self.sequence = 0
        self.total_tokens = 0
        
        # Callbacks
        self.on_chunk: Optional[Callable] = None
        self.on_complete: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        
        # Cancellation
        self.cancelled = False
        self.cancel_event = asyncio.Event()
    
    def add_chunk(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> StreamChunk:
        """Add a chunk to the stream."""
        chunk = StreamChunk(
            stream_id=self.stream_id,
            sequence=self.sequence,
            content=content,
            metadata=metadata,
        )
        
        self.chunks.append(chunk)
        self.sequence += 1
        
        # Update token count (rough estimate)
        self.total_tokens += len(content.split())
        
        return chunk
    
    def get_full_content(self) -> str:
        """Get complete content from all chunks."""
        return "".join(chunk.content for chunk in self.chunks)
    
    def cancel(self):
        """Cancel the stream."""
        self.cancelled = True
        self.cancel_event.set()
        self.state = StreamState.CANCELLED
        logger.info(f"Stream {self.stream_id} cancelled")
    
    def is_active(self) -> bool:
        """Check if stream is active."""
        return self.state in (StreamState.PENDING, StreamState.STREAMING)
    
    def duration_ms(self) -> float:
        """Get stream duration in milliseconds."""
        if not self.start_time:
            return 0.0
        
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
        return {
            "stream_id": self.stream_id,
            "user_id": self.user_id,
            "state": self.state,
            "chunks": len(self.chunks),
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms(),
            "full_content": self.get_full_content() if self.state == StreamState.COMPLETED else None,
        }


class StreamingHandler:
    """
    Handles streaming AI responses with minimal latency.
    
    Features:
    - Immediate chunk forwarding (no buffering delay)
    - Multiple concurrent streams per user
    - Stream cancellation
    - Progress updates
    - Error recovery
    """
    
    def __init__(
        self,
        llm_client: Optional[Any] = None,
        max_concurrent_streams: int = 10,
    ):
        """
        Initialize streaming handler.
        
        Args:
            llm_client: LLM client with streaming support
            max_concurrent_streams: Max concurrent streams per user
        """
        self.llm_client = llm_client
        self.max_concurrent_streams = max_concurrent_streams
        
        # Active streams
        self.streams: Dict[str, StreamSession] = {}
        
        # Metrics
        self.total_streams = 0
        self.completed_streams = 0
        self.cancelled_streams = 0
        self.error_streams = 0
    
    async def start_stream(
        self,
        stream_id: str,
        user_id: str,
        prompt: str,
        on_chunk: Callable[[StreamChunk], None],
        on_complete: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        **llm_params,
    ) -> StreamSession:
        """
        Start a new streaming session.
        
        Args:
            stream_id: Unique stream ID
            user_id: User ID
            prompt: LLM prompt
            on_chunk: Callback for each chunk
            on_complete: Optional completion callback
            on_error: Optional error callback
            **llm_params: Additional LLM parameters
            
        Returns:
            StreamSession
        """
        # Create session
        session = StreamSession(
            stream_id=stream_id,
            user_id=user_id,
            request_params={"prompt": prompt, **llm_params},
        )
        
        session.on_chunk = on_chunk
        session.on_complete = on_complete
        session.on_error = on_error
        
        # Store session
        self.streams[stream_id] = session
        self.total_streams += 1
        
        # Start streaming in background
        asyncio.create_task(self._stream_llm_response(session, prompt, llm_params))
        
        logger.info(f"🎬 Stream started: {stream_id} | User: {user_id}")
        
        return session
    
    async def _stream_llm_response(
        self,
        session: StreamSession,
        prompt: str,
        llm_params: Dict[str, Any],
    ):
        """Stream LLM response and forward chunks."""
        session.state = StreamState.STREAMING
        session.start_time = time.time()
        
        try:
            # Stream from LLM
            if self.llm_client:
                async for chunk_content in self._llm_stream(prompt, llm_params):
                    # Check for cancellation
                    if session.cancelled:
                        logger.info(f"Stream {session.stream_id} cancelled during generation")
                        break
                    
                    # Add chunk
                    chunk = session.add_chunk(chunk_content)
                    
                    # Forward to callback
                    if session.on_chunk:
                        try:
                            result = session.on_chunk(chunk)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"Error in chunk callback: {e}")
            else:
                # Mock streaming for testing
                mock_response = "This is a mock streaming response. " * 10
                words = mock_response.split()
                
                for i, word in enumerate(words):
                    if session.cancelled:
                        break
                    
                    chunk = session.add_chunk(word + " ")
                    
                    if session.on_chunk:
                        try:
                            result = session.on_chunk(chunk)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"Error in chunk callback: {e}")
                    
                    # Small delay to simulate streaming
                    await asyncio.sleep(0.05)
            
            # Mark as completed
            if session.cancelled:
                session.state = StreamState.CANCELLED
                self.cancelled_streams += 1
            else:
                session.state = StreamState.COMPLETED
                session.end_time = time.time()
                self.completed_streams += 1
                
                # Call completion callback
                if session.on_complete:
                    try:
                        result = session.on_complete(session)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        logger.error(f"Error in complete callback: {e}")
            
            logger.info(
                f"✅ Stream completed: {session.stream_id} | "
                f"Chunks: {len(session.chunks)} | "
                f"Tokens: {session.total_tokens} | "
                f"Duration: {session.duration_ms():.0f}ms"
            )
        
        except Exception as e:
            logger.exception(f"❌ Stream error: {session.stream_id}")
            session.state = StreamState.ERROR
            session.end_time = time.time()
            self.error_streams += 1
            
            # Call error callback
            if session.on_error:
                try:
                    result = session.on_error(e)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as callback_error:
                    logger.error(f"Error in error callback: {callback_error}")
    
    async def _llm_stream(
        self,
        prompt: str,
        params: Dict[str, Any],
    ) -> AsyncIterator[str]:
        """Stream from LLM client."""
        # This would call actual LLM streaming API
        # For now, mock implementation
        
        if hasattr(self.llm_client, "stream"):
            async for chunk in self.llm_client.stream(prompt, **params):
                yield chunk
        else:
            # Fallback mock
            words = "Mock streaming response from LLM client".split()
            for word in words:
                await asyncio.sleep(0.05)
                yield word + " "
    
    def get_stream(self, stream_id: str) -> Optional[StreamSession]:
        """Get stream session by ID."""
        return self.streams.get(stream_id)
    
    def cancel_stream(self, stream_id: str) -> bool:
        """Cancel an active stream."""
        session = self.streams.get(stream_id)
        if not session:
            return False
        
        if session.is_active():
            session.cancel()
            return True
        
        return False
    
    def cleanup_stream(self, stream_id: str):
        """Remove completed/cancelled stream from memory."""
        if stream_id in self.streams:
            session = self.streams[stream_id]
            if not session.is_active():
                del self.streams[stream_id]
                logger.debug(f"Cleaned up stream: {stream_id}")
    
    def get_user_streams(self, user_id: str) -> list[StreamSession]:
        """Get all streams for a user."""
        return [s for s in self.streams.values() if s.user_id == user_id]
    
    def get_active_streams(self) -> list[StreamSession]:
        """Get all active streams."""
        return [s for s in self.streams.values() if s.is_active()]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics."""
        active_streams = self.get_active_streams()
        
        # Calculate average streaming time for completed
        completed = [s for s in self.streams.values() if s.state == StreamState.COMPLETED]
        avg_duration = sum(s.duration_ms() for s in completed) / len(completed) if completed else 0
        
        return {
            "streams": {
                "active": len(active_streams),
                "total": len(self.streams),
            },
            "lifetime": {
                "total": self.total_streams,
                "completed": self.completed_streams,
                "cancelled": self.cancelled_streams,
                "errors": self.error_streams,
            },
            "performance": {
                "avg_duration_ms": f"{avg_duration:.0f}",
            },
        }


class StreamManager:
    """
    High-level manager for streaming across WebSocket/SSE.
    
    Integrates StreamingHandler with connection pool for automatic
    forwarding of chunks to clients.
    """
    
    def __init__(
        self,
        connection_pool: Optional[Any] = None,
        streaming_handler: Optional[StreamingHandler] = None,
    ):
        """
        Initialize stream manager.
        
        Args:
            connection_pool: Connection pool for sending chunks
            streaming_handler: Streaming handler instance
        """
        self.connection_pool = connection_pool
        self.handler = streaming_handler or StreamingHandler()
    
    async def stream_to_client(
        self,
        stream_id: str,
        user_id: str,
        prompt: str,
        **llm_params,
    ) -> StreamSession:
        """
        Start streaming AI response directly to client.
        
        Automatically forwards chunks via WebSocket as they arrive.
        
        Args:
            stream_id: Unique stream ID
            user_id: User ID
            prompt: LLM prompt
            **llm_params: LLM parameters
            
        Returns:
            StreamSession
        """
        # Define chunk callback
        async def send_chunk(chunk: StreamChunk):
            """Send chunk to client via WebSocket."""
            if self.connection_pool:
                await self.connection_pool.send_to_user(
                    user_id,
                    {
                        "type": "stream_chunk",
                        "stream_id": stream_id,
                        "sequence": chunk.sequence,
                        "content": chunk.content,
                        "timestamp": chunk.timestamp,
                    }
                )
        
        # Define completion callback
        async def send_complete(session: StreamSession):
            """Send completion message to client."""
            if self.connection_pool:
                await self.connection_pool.send_to_user(
                    user_id,
                    {
                        "type": "stream_complete",
                        "stream_id": stream_id,
                        "full_content": session.get_full_content(),
                        "total_tokens": session.total_tokens,
                        "duration_ms": session.duration_ms(),
                    }
                )
        
        # Define error callback
        async def send_error(error: Exception):
            """Send error message to client."""
            if self.connection_pool:
                await self.connection_pool.send_to_user(
                    user_id,
                    {
                        "type": "stream_error",
                        "stream_id": stream_id,
                        "error": str(error),
                    }
                )
        
        # Start streaming
        session = await self.handler.start_stream(
            stream_id=stream_id,
            user_id=user_id,
            prompt=prompt,
            on_chunk=send_chunk,
            on_complete=send_complete,
            on_error=send_error,
            **llm_params,
        )
        
        return session
    
    async def cancel_stream(self, stream_id: str) -> bool:
        """Cancel a stream."""
        return self.handler.cancel_stream(stream_id)
    
    def get_stream(self, stream_id: str) -> Optional[StreamSession]:
        """Get stream session."""
        return self.handler.get_stream(stream_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics."""
        return self.handler.get_stats()
