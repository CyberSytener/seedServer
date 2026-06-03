"""
Optimized Realtime Server Integration Example

Complete example showing how to integrate all optimized components
for handling high-frequency client requests with minimal latency.
"""

import asyncio
import logging
from typing import Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager

# Import optimized components
from app.core.realtime.optimized.realtime_handler import (
    OptimizedRealtimeHandler,
    OptimizedRequest,
    RequestType,
    RequestPriority,
)
from app.core.realtime.optimized.connection_pool import ConnectionPool
from app.core.realtime.optimized.streaming_handler import StreamingHandler, StreamManager
from app.core.realtime.optimized.fast_saga_processor import FastSagaProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# EXAMPLE 1: Initialize All Components
# ============================================================================

# Global instances (would be in dependency injection in production)
connection_pool: ConnectionPool = None
realtime_handler: OptimizedRealtimeHandler = None
stream_manager: StreamManager = None
fast_saga_processor: FastSagaProcessor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context for startup/shutdown."""
    global connection_pool, realtime_handler, stream_manager, fast_saga_processor
    
    # Startup
    logger.info("🚀 Starting optimized realtime server...")
    
    # Initialize connection pool
    connection_pool = ConnectionPool(
        max_connections=1000,
        ping_interval=30,
        cleanup_interval=60,
    )
    await connection_pool.start()
    
    # Initialize streaming handler
    streaming_handler = StreamingHandler(
        llm_client=None,  # Replace with actual LLM client
        max_concurrent_streams=10,
    )
    
    stream_manager = StreamManager(
        connection_pool=connection_pool,
        streaming_handler=streaming_handler,
    )
    
    # Initialize fast saga processor
    fast_saga_processor = FastSagaProcessor(
        saga_orchestrator=None,  # Replace with actual saga orchestrator
        connection_pool=connection_pool,
        max_parallel_per_user=5,
        progress_update_interval=0.5,
    )
    
    # Initialize optimized handler
    realtime_handler = OptimizedRealtimeHandler(
        saga_orchestrator=None,  # Replace with actual saga orchestrator
        llm_client=None,        # Replace with actual LLM client
        max_concurrent=50,
        cache_ttl=300,
    )
    await realtime_handler.start()
    
    logger.info("✅ All components initialized")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down optimized realtime server...")
    
    await realtime_handler.stop()
    await connection_pool.stop()
    
    logger.info("✅ Shutdown complete")


app = FastAPI(lifespan=lifespan)


# ============================================================================
# EXAMPLE 2: WebSocket Endpoint with Optimized Handler
# ============================================================================

@app.websocket("/ws/realtime")
async def realtime_websocket(websocket: WebSocket):
    """
    Optimized WebSocket endpoint for high-frequency client requests.
    
    Handles:
    - Multiple small requests per second
    - Parallel saga execution
    - Streaming AI responses
    - Real-time progress updates
    """
    await websocket.accept()
    
    # Get user_id from connection (simplified)
    user_id = "user_123"  # Would extract from auth token
    
    # Add connection to pool
    conn = await connection_pool.add_connection(websocket, user_id)
    
    logger.info(f"✅ Client connected: {user_id} | Connection: {conn.connection_id}")
    
    try:
        while True:
            # Receive message from client
            message = await websocket.receive_json()
            
            # Route to appropriate handler
            await handle_client_message(user_id, message, websocket)
    
    except WebSocketDisconnect:
        logger.info(f"🔌 Client disconnected: {user_id}")
    except Exception as e:
        logger.exception(f"❌ WebSocket error: {e}")
    finally:
        # Remove connection from pool
        await connection_pool.remove_connection(user_id)


async def handle_client_message(
    user_id: str,
    message: Dict[str, Any],
    websocket: WebSocket,
):
    """Handle incoming client message with optimized routing."""
    
    message_type = message.get("type")
    request_id = message.get("request_id", "unknown")
    
    logger.debug(f"📥 Message from {user_id}: {message_type}")
    
    # Route based on message type
    if message_type == "saga.start":
        await handle_saga_start(user_id, message, websocket)
    
    elif message_type == "saga.query":
        await handle_saga_query(user_id, message, websocket)
    
    elif message_type == "ai.complete":
        await handle_ai_completion(user_id, message, websocket)
    
    elif message_type == "ai.stream":
        await handle_ai_stream(user_id, message, websocket)
    
    elif message_type == "context.store":
        await handle_context_store(user_id, message, websocket)
    
    elif message_type == "ping":
        # Fast-path ping/pong
        await websocket.send_json({
            "type": "pong",
            "request_id": request_id,
            "timestamp": message.get("timestamp"),
        })
    
    else:
        logger.warning(f"Unknown message type: {message_type}")
        await websocket.send_json({
            "type": "error",
            "request_id": request_id,
            "error": f"Unknown message type: {message_type}",
        })


# ============================================================================
# EXAMPLE 3: Saga Start with Fast Processor
# ============================================================================

async def handle_saga_start(
    user_id: str,
    message: Dict[str, Any],
    websocket: WebSocket,
):
    """
    Handle saga start with fast-path optimization.
    
    Client sends:
    {
        "type": "saga.start",
        "request_id": "req_123",
        "saga_type": "cv_generation",
        "params": {...},
        "context_snippet": "User has 5 years Python experience..." // 90% token reduction
    }
    """
    request_id = message.get("request_id")
    saga_type = message.get("saga_type")
    params = message.get("params", {})
    context_snippet = message.get("context_snippet")
    
    # Start saga with fast processor
    saga_id = await fast_saga_processor.start_saga_fast(
        user_id=user_id,
        saga_type=saga_type,
        payload=params,
        context_snippet=context_snippet,
        action_id=request_id,
    )
    
    # Register saga with connection pool
    connection_pool.register_saga(saga_id, user_id)
    
    # Send immediate response
    await websocket.send_json({
        "type": "saga.started",
        "request_id": request_id,
        "saga_id": saga_id,
        "status": "processing",
    })
    
    logger.info(f"✅ Saga started: {saga_id} for user {user_id}")


# ============================================================================
# EXAMPLE 4: Fast Saga Query (<100ms)
# ============================================================================

async def handle_saga_query(
    user_id: str,
    message: Dict[str, Any],
    websocket: WebSocket,
):
    """
    Handle saga query with fast-path (<100ms response).
    
    Client sends:
    {
        "type": "saga.query",
        "request_id": "req_124",
        "saga_id": "saga_abc123"
    }
    """
    request_id = message.get("request_id")
    saga_id = message.get("saga_id")
    
    # Fast-path query from memory (<1ms)
    progress = fast_saga_processor.get_saga_progress(saga_id)
    
    if progress:
        await websocket.send_json({
            "type": "saga.status",
            "request_id": request_id,
            "saga_id": saga_id,
            "data": progress.to_dict(),
        })
    else:
        await websocket.send_json({
            "type": "saga.not_found",
            "request_id": request_id,
            "saga_id": saga_id,
        })


# ============================================================================
# EXAMPLE 5: AI Completion (Non-Streaming)
# ============================================================================

async def handle_ai_completion(
    user_id: str,
    message: Dict[str, Any],
    websocket: WebSocket,
):
    """
    Handle AI completion request.
    
    Client sends:
    {
        "type": "ai.complete",
        "request_id": "req_125",
        "prompt": "Write a professional summary...",
        "context_snippet": "User is Python developer..." // Optional context
    }
    """
    request_id = message.get("request_id")
    prompt = message.get("prompt")
    context_snippet = message.get("context_snippet")
    
    # Create optimized request
    request = OptimizedRequest(
        request_id=request_id,
        user_id=user_id,
        request_type=RequestType.AI_COMPLETION,
        priority=RequestPriority.HIGH,
        payload={"prompt": prompt},
        context_snippet=context_snippet,
    )
    
    # Handle with optimized handler
    response = await realtime_handler.handle_request(request)
    
    # Send response
    await websocket.send_json({
        "type": "ai.complete",
        "request_id": request_id,
        "data": response.data,
        "meta": {
            "processing_time_ms": response.processing_time_ms,
            "cached": response.cached,
        },
    })


# ============================================================================
# EXAMPLE 6: AI Streaming
# ============================================================================

async def handle_ai_stream(
    user_id: str,
    message: Dict[str, Any],
    websocket: WebSocket,
):
    """
    Handle AI streaming request.
    
    Client sends:
    {
        "type": "ai.stream",
        "request_id": "req_126",
        "stream_id": "stream_123",
        "prompt": "Generate detailed CV..."
    }
    
    Server streams back:
    {
        "type": "stream_chunk",
        "stream_id": "stream_123",
        "content": "Professional ",
        "sequence": 0
    }
    """
    request_id = message.get("request_id")
    stream_id = message.get("stream_id", request_id)
    prompt = message.get("prompt")
    
    # Start streaming with stream manager
    # Stream manager automatically forwards chunks to client via WebSocket
    session = await stream_manager.stream_to_client(
        stream_id=stream_id,
        user_id=user_id,
        prompt=prompt,
    )
    
    # Send acknowledgment
    await websocket.send_json({
        "type": "stream.started",
        "request_id": request_id,
        "stream_id": stream_id,
    })
    
    logger.info(f"🎬 Stream started: {stream_id} for user {user_id}")


# ============================================================================
# EXAMPLE 7: Context Store
# ============================================================================

async def handle_context_store(
    user_id: str,
    message: Dict[str, Any],
    websocket: WebSocket,
):
    """
    Handle context store request.
    
    Client stores full data locally (IndexedDB) and sends only reference:
    {
        "type": "context.store",
        "request_id": "req_127",
        "reference_id": "cv_draft_v5",
        "snippet": "Senior Python Engineer with 5+ years..." // Short context
    }
    
    Server stores reference, can request full data later if needed.
    """
    request_id = message.get("request_id")
    reference_id = message.get("reference_id")
    snippet = message.get("snippet")
    
    # Create optimized request
    request = OptimizedRequest(
        request_id=request_id,
        user_id=user_id,
        request_type=RequestType.CONTEXT_STORE,
        priority=RequestPriority.LOW,
        payload={"reference_id": reference_id},
        context_snippet=snippet,
        reference_id=reference_id,
    )
    
    # Handle with optimized handler
    response = await realtime_handler.handle_request(request)
    
    # Send acknowledgment
    await websocket.send_json({
        "type": "context.stored",
        "request_id": request_id,
        "reference_id": reference_id,
    })


# ============================================================================
# EXAMPLE 8: Stats Endpoint
# ============================================================================

@app.get("/api/stats/realtime")
async def get_realtime_stats():
    """Get real-time statistics."""
    return {
        "connection_pool": connection_pool.get_stats() if connection_pool else {},
        "realtime_handler": realtime_handler.get_stats() if realtime_handler else {},
        "stream_manager": stream_manager.get_stats() if stream_manager else {},
        "fast_saga_processor": fast_saga_processor.get_stats() if fast_saga_processor else {},
    }


# ============================================================================
# EXAMPLE 9: Run Standalone Server
# ============================================================================

async def example_standalone():
    """
    Run standalone server for testing.
    
    Usage:
        python integration_example.py
    """
    import uvicorn
    
    print("""
    ============================================================================
    Optimized Realtime Server - Integration Example
    ============================================================================
    
    WebSocket: ws://localhost:8000/ws/realtime
    Stats:     http://localhost:8000/api/stats/realtime
    
    Features:
    - High-frequency request handling (10-100 req/sec per client)
    - Parallel saga execution
    - Streaming AI responses
    - Sub-100ms query responses
    - Context optimization (90% token reduction)
    
    ============================================================================
    """)
    
    # Run server
    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


# ============================================================================
# EXAMPLE 10: Client Integration (Python Example)
# ============================================================================

async def example_client():
    """
    Example Python client showing optimized request patterns.
    
    In production, this would be your TypeScript/React client.
    """
    import websockets
    import json
    
    async with websockets.connect("ws://localhost:8000/ws/realtime") as websocket:
        print("✅ Connected to server")
        
        # Example 1: Start a saga with context snippet
        await websocket.send(json.dumps({
            "type": "saga.start",
            "request_id": "req_001",
            "saga_type": "cv_generation",
            "params": {
                "target_role": "Senior Python Engineer",
                "style": "professional",
            },
            "context_snippet": "5+ years Python, FastAPI, PostgreSQL expertise"  # 90% smaller!
        }))
        
        response = await websocket.recv()
        saga_data = json.loads(response)
        saga_id = saga_data.get("saga_id")
        print(f"✅ Saga started: {saga_id}")
        
        # Example 2: Query saga progress (fast-path)
        await websocket.send(json.dumps({
            "type": "saga.query",
            "request_id": "req_002",
            "saga_id": saga_id,
        }))
        
        response = await websocket.recv()
        progress = json.loads(response)
        print(f"📊 Progress: {progress.get('data', {}).get('percentage')}%")
        
        # Example 3: Start streaming AI
        await websocket.send(json.dumps({
            "type": "ai.stream",
            "request_id": "req_003",
            "stream_id": "stream_001",
            "prompt": "Generate professional summary",
        }))
        
        # Receive stream chunks
        print("🎬 Streaming started, receiving chunks...")
        chunk_count = 0
        while chunk_count < 10:  # Receive first 10 chunks
            response = await websocket.recv()
            chunk = json.loads(response)
            
            if chunk.get("type") == "stream_chunk":
                print(f"   Chunk {chunk.get('sequence')}: {chunk.get('content')}")
                chunk_count += 1
            elif chunk.get("type") == "stream_complete":
                print("✅ Streaming completed")
                break
        
        print("\n✅ Client example completed")


# ============================================================================
# Run Examples
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "client":
        # Run client example
        asyncio.run(example_client())
    else:
        # Run server
        asyncio.run(example_standalone())

