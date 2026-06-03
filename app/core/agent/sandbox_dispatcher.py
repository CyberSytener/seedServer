"""Sandbox RPC dispatcher (Phase 7 — P7-15).

API-side component that dispatches tool calls to the isolated sandbox worker
via Redis queues and waits for results.

Flow:
  1. API builds an RPC request (rpc_id, session_id, tool_name, tool_input, session_token)
  2. Pushes to ``agent_sandbox_rpc`` queue
  3. Waits on ``agent_sandbox_rpc_result:{rpc_id}`` via BLPOP (with timeout)
  4. Returns parsed result or timeout error
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RPC_QUEUE = "agent_sandbox_rpc"
RESULT_QUEUE_PREFIX = "agent_sandbox_rpc_result:"
DEFAULT_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

class SandboxDispatcher:
    """Dispatches tool calls to the sandbox worker via Redis RPC.

    Parameters
    ----------
    redis_client:
        A ``redis.Redis`` (or compatible) instance with ``rpush``, ``blpop``, ``delete``.
    token_issuer:
        Optional callable ``(session_id, tool_name, rpc_id) -> str`` that
        produces a scoped JWT for sandbox authentication.
    timeout:
        Seconds to wait for sandbox response (default: 30).
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        token_issuer: Any = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._redis = redis_client
        self._token_issuer = token_issuer
        self._timeout = timeout

    def dispatch(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Dispatch a tool call to the sandbox worker and wait for the result.

        Returns a dict with keys: ``rpc_id``, ``status``, ``tool_output``,
        ``duration_ms``, ``error``.
        """
        rpc_id = str(uuid.uuid4())
        effective_timeout = timeout if timeout is not None else self._timeout

        # Issue session token if issuer is available
        session_token: Optional[str] = None
        if self._token_issuer is not None:
            try:
                session_token = self._token_issuer(session_id, tool_name, rpc_id)
            except Exception:
                logger.warning("Failed to issue sandbox token for rpc_id=%s", rpc_id)

        # Build RPC request
        rpc_request = {
            "rpc_id": rpc_id,
            "session_id": session_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "session_token": session_token,
            "timeout_seconds": effective_timeout,
        }

        result_key = f"{RESULT_QUEUE_PREFIX}{rpc_id}"

        try:
            # Push to sandbox RPC queue
            self._redis.rpush(RPC_QUEUE, json.dumps(rpc_request))

            # Wait for result (BLPOP)
            item = self._redis.blpop(result_key, timeout=effective_timeout)
            if item is None:
                logger.warning("Sandbox RPC timeout for rpc_id=%s", rpc_id)
                return {
                    "rpc_id": rpc_id,
                    "status": "timeout",
                    "tool_output": None,
                    "duration_ms": effective_timeout * 1000,
                    "error": f"Sandbox timeout after {effective_timeout}s",
                }

            # Parse result
            _, raw = item
            result = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
            return result

        except Exception as exc:
            logger.error("Sandbox RPC error for rpc_id=%s: %s", rpc_id, exc)
            return {
                "rpc_id": rpc_id,
                "status": "error",
                "tool_output": None,
                "duration_ms": 0,
                "error": str(exc),
            }
        finally:
            # Clean up result queue
            try:
                self._redis.delete(result_key)
            except Exception:
                pass
