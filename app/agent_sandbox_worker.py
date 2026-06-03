"""Agent sandbox worker entrypoint (Phase 7 — P7-14 / P7-15).

Runs in an isolated container with:
- No SEED_OPENAI_API_KEY or database credentials
- Read-only rootfs + /work tmpfs
- Internal-only Docker network (no external egress)
- Communicates with API server exclusively via Redis RPC queues

Usage (inside container):
    python -m app.agent_sandbox_worker
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, Optional, Set

logger = logging.getLogger("agent_sandbox_worker")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RPC_QUEUE = "agent_sandbox_rpc"
RESULT_QUEUE_PREFIX = "agent_sandbox_rpc_result:"
POLL_TIMEOUT = 5  # seconds for BLPOP
MAX_REPLAY_CACHE = 10_000

# ---------------------------------------------------------------------------
# Replay protection (in-memory LRU-like set)
# ---------------------------------------------------------------------------

_seen_rpc_ids: Set[str] = set()
_seen_rpc_order: list = []


def _track_rpc_id(rpc_id: str) -> bool:
    """Track rpc_id. Returns True if already seen (replay)."""
    if rpc_id in _seen_rpc_ids:
        return True
    _seen_rpc_ids.add(rpc_id)
    _seen_rpc_order.append(rpc_id)
    # Evict oldest if over capacity
    while len(_seen_rpc_order) > MAX_REPLAY_CACHE:
        old = _seen_rpc_order.pop(0)
        _seen_rpc_ids.discard(old)
    return False


# ---------------------------------------------------------------------------
# Tool allowlist (defense-in-depth)
# ---------------------------------------------------------------------------

def _load_sandbox_allowlist() -> Set[str]:
    """Load tools with `allowed_in_sandbox: true` from tool_permissions.yaml."""
    try:
        from app.core.agent.tool_registry import ToolPermissionConfig
        cfg = ToolPermissionConfig.from_yaml()
        allowed = set()
        # Check all configured tools
        for tool_name in cfg._tools:
            if cfg.allowed_in_sandbox(tool_name):
                allowed.add(tool_name)
        return allowed
    except Exception:
        logger.warning("Failed to load tool_permissions.yaml; sandbox allowlist empty")
        return set()


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

def _validate_session_token(token: str, expected_rpc_id: str, expected_tool: str) -> bool:
    """Validate the scoped JWT for sandbox RPC.

    Checks audience, issuer, expiry, and claims.
    Returns True if valid, False otherwise.
    """
    try:
        from app.core.security.jwt import decode_token
        payload = decode_token(
            token,
            audience="seed:sandbox",
            issuer="seed:api",
            secret_key=os.environ.get("SEED_SANDBOX_JWT_SECRET"),
        )
        if payload.get("rpc_id") != expected_rpc_id:
            logger.warning("Token rpc_id mismatch")
            return False
        if payload.get("tool_name") != expected_tool:
            logger.warning("Token tool_name mismatch")
            return False
        return True
    except Exception as exc:
        logger.warning("Token validation failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Job processor
# ---------------------------------------------------------------------------

def _process_job(
    job: Dict[str, Any],
    sandbox_allowlist: Set[str],
) -> Dict[str, Any]:
    """Process a single sandbox RPC job.

    Returns the result dict to push to the result queue.
    """
    rpc_id = job.get("rpc_id", "unknown")
    tool_name = job.get("tool_name", "")
    tool_input = job.get("tool_input", {})

    # Replay check
    if _track_rpc_id(rpc_id):
        return {
            "rpc_id": rpc_id,
            "status": "error",
            "tool_output": None,
            "duration_ms": 0,
            "error": "Replayed rpc_id",
        }

    # Allowlist check
    if tool_name not in sandbox_allowlist:
        return {
            "rpc_id": rpc_id,
            "status": "error",
            "tool_output": None,
            "duration_ms": 0,
            "error": f"Tool '{tool_name}' not allowed in sandbox",
        }

    # Token validation (optional: only if token is provided)
    session_token = job.get("session_token")
    if session_token:
        if not _validate_session_token(session_token, rpc_id, tool_name):
            return {
                "rpc_id": rpc_id,
                "status": "error",
                "tool_output": None,
                "duration_ms": 0,
                "error": "Invalid session token",
            }

    # Execute tool via BlockRegistry
    t0 = time.monotonic()
    try:
        from app.core.blocks import BlockRegistry
        block_registry = BlockRegistry()
        block_cls = block_registry.get_block(tool_name)
        if block_cls is None:
            raise ValueError(f"Block '{tool_name}' not registered")
        block = block_cls()
        result = block.execute(tool_input)
        duration_ms = (time.monotonic() - t0) * 1000
        return {
            "rpc_id": rpc_id,
            "status": "success",
            "tool_output": result,
            "duration_ms": duration_ms,
            "error": None,
        }
    except Exception as exc:
        duration_ms = (time.monotonic() - t0) * 1000
        return {
            "rpc_id": rpc_id,
            "status": "error",
            "tool_output": None,
            "duration_ms": duration_ms,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    """Sandbox worker main loop: poll Redis RPC queue, execute, respond."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    logger.info("Agent sandbox worker starting (SEED_SANDBOX_MODE=%s)", os.environ.get("SEED_SANDBOX_MODE"))

    # Verify isolation: no secret keys
    for forbidden in ("SEED_OPENAI_API_KEY", "DATABASE_URL", "SEED_DB_PATH"):
        if forbidden in os.environ:
            logger.error("SECURITY: %s found in sandbox env — aborting!", forbidden)
            sys.exit(1)

    sandbox_allowlist = _load_sandbox_allowlist()
    logger.info("Sandbox allowlist: %s", sandbox_allowlist or "(empty)")

    redis_url = os.environ.get("SEED_REDIS_URL", "redis://localhost:6379/0")

    try:
        import redis as redis_lib
        r = redis_lib.from_url(redis_url, decode_responses=True)
        r.ping()
        logger.info("Connected to Redis at %s", redis_url)
    except Exception as exc:
        logger.error("Failed to connect to Redis: %s", exc)
        sys.exit(1)

    running = True

    def _shutdown(sig, frame):
        nonlocal running
        logger.info("Received signal %s, shutting down…", sig)
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while running:
        try:
            # BLPOP with timeout
            item = r.blpop(RPC_QUEUE, timeout=POLL_TIMEOUT)
            if item is None:
                continue

            _, raw = item
            job = json.loads(raw)
            rpc_id = job.get("rpc_id", "unknown")
            logger.info("Processing RPC %s: tool=%s", rpc_id, job.get("tool_name"))

            result = _process_job(job, sandbox_allowlist)

            # Push result to per-RPC result queue
            result_key = f"{RESULT_QUEUE_PREFIX}{rpc_id}"
            r.rpush(result_key, json.dumps(result))
            r.expire(result_key, 120)  # Expire after 2 minutes

            logger.info("Completed RPC %s: status=%s", rpc_id, result["status"])

        except json.JSONDecodeError:
            logger.warning("Invalid JSON in RPC queue")
        except Exception:
            logger.exception("Error processing sandbox job")
            time.sleep(1)

    logger.info("Sandbox worker stopped.")


if __name__ == "__main__":
    main()
