"""
Saga Orchestrator for STEP 4: Multi-step external flows with compensation.

Handles:
- Multi-step saga execution (reserve → confirm → finalize)
- Two-phase commits (tentative → confirmed)
- Compensation on failure (rollback)
- Persistence across process restarts
- Idempotency via saga_id
- Distributed locking for state transitions
- Timeout enforcement and automatic compensation
- Circuit breaker for adapter resilience
- Retry logic with exponential backoff
- Distributed tracing with correlation_id

Architecture:
  ActionRouter (STEP 2)
    ↓
  SagaOrchestrator (STEP 4)
    ├→ Distributed Lock (Redis)
    ├→ Idempotency Check
    ├→ Adapter.reserve() (tentative) + Circuit Breaker + Retry
    ├→ Persist to DB (waiting_confirm state)
    ├→ [Client confirms]
    ├→ Adapter.confirm() (committed) + Circuit Breaker + Retry
    └→ Compensation with ordering (LIFO) if needed
"""

import uuid
import json
import logging
import asyncio
import time
import os
import inspect
import hashlib
from typing import Any, Awaitable, Dict, List, Optional, Callable
from datetime import datetime, timedelta, timezone
from collections import defaultdict

try:
    import redis.asyncio as redis
except ImportError:
    try:
        import redis
    except ImportError:
        redis = None

# Import production modules
from app.core.realtime.sagas.saga_metrics import SagaMetricsCollector, SagaMetrics, PrometheusSagaMetrics
from app.core.realtime.sagas.saga_telemetry import SagaTelemetryCollector
from app.core.realtime.sagas.saga_rate_limiter import RateLimiter, RateLimitPolicy, RedisRateLimiter
from app.core.realtime.sagas.saga_dlq import DeadLetterQueue, DLQMessage, DLQMessageType
from app.core.realtime.engine import (
    TTLCache,
    BaseSaga,
    CompensationAction,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    DistributedLock,
    RETRY_CONFIGS,
    RetryConfig,
    SagaState,
    SagaStepRecord,
    SagaStepDefinition,
    SagaStepResult,
    StepStatus,
    retry_with_backoff,
)
from app.core.interfaces.database import AsyncDatabaseProtocol
from app.core.realtime.sagas.flows import (
    BookingFlow,
    CalendarFlow,
    CVGenerationFlow,
    LearningPlanFlow,
    DiagnosticCoreFlow,
    CareerGrowthFlow,
    CareerUpskillingFlow,
    UpskillingLoopFlow,
    MarketWatcherFlow,
    NeoEatsOrderFlow,
    LLMPipelineFlow,
    FlowExecutorSaga,
)

logger = logging.getLogger(__name__)


# =========================================================================
# TTL Cache for Idempotency (with size limit and expiration)
# =========================================================================

# =========================================================================
# Saga Configuration (Timeouts and Retry Policies)
# =========================================================================

# Per-saga-type timeout configuration
SAGA_TIMEOUTS = {
    "booking_flow": timedelta(hours=24),
    "calendar_flow": timedelta(hours=1),
    "payment_flow": timedelta(minutes=15),
    "cv_generation": timedelta(minutes=10),
    "learning_plan": timedelta(minutes=5),
    "diagnostic_core": timedelta(minutes=15),
    "career_growth_flow": timedelta(minutes=30),
    "market_watcher": timedelta(hours=2),
    "upskilling_loop": timedelta(days=30),
    "neoeats_order": timedelta(minutes=5),
    "llm_pipeline": timedelta(minutes=10),
    "flow_executor": timedelta(minutes=15),
}

# Versioned saga definitions (handlers are resolved by saga_version)
SAGA_VERSION_REGISTRY = {
    "booking_flow": {
        "current": "v1",
        "handlers": {"v1": BookingFlow},
        "resume_handlers": {"v1": BookingFlow},
    },
    "calendar_flow": {
        "current": "v1",
        "handlers": {"v1": CalendarFlow},
    },
    "cv_generation": {
        "current": "v1",
        "handlers": {"v1": CVGenerationFlow},
    },
    "learning_plan": {
        "current": "v1",
        "handlers": {"v1": LearningPlanFlow},
    },
    "diagnostic_core": {
        "current": "v1",
        "handlers": {"v1": DiagnosticCoreFlow},
    },
    "career_upskilling": {
        "current": "v1",
        "handlers": {"v1": UpskillingLoopFlow},
        "resume_handlers": {"v1": UpskillingLoopFlow},
    },
    "market_watcher": {
        "current": "v1",
        "handlers": {"v1": MarketWatcherFlow},
    },
    "upskilling_loop": {
        "current": "v1",
        "handlers": {"v1": UpskillingLoopFlow},
        "resume_handlers": {"v1": UpskillingLoopFlow},
    },
    "career_growth_flow": {
        "current": "v1",
        "handlers": {"v1": CareerGrowthFlow},
    },
    "neoeats_order": {
        "current": "v1",
        "handlers": {"v1": NeoEatsOrderFlow},
    },
    "llm_pipeline": {
        "current": "v1",
        "handlers": {"v1": LLMPipelineFlow},
    },
    "flow_executor": {
        "current": "v1",
        "handlers": {"v1": FlowExecutorSaga},
    },
}

# Maximum time to keep sagas waiting for confirmation (default: 30 days)
WAITING_CONFIRM_TTL_SECONDS = int(os.getenv("SAGA_WAITING_CONFIRM_TTL_SECONDS", str(30 * 24 * 3600)))

# Fallback mapping for compensation (legacy steps without adapter_type)
COMPENSATION_STEP_MAP = {
    "reserve_slot": "booking",
    "create_event": "calendar",
}


class SagaOrchestrator:
    """
    Orchestrates multi-step external flows (sagas) with compensation.
    
    Key responsibilities:
    1. Create saga and persist initial state
    2. Execute saga steps (adapters)
    3. Handle confirmation workflow
    4. Trigger compensation on failure
    5. Track all operations in audit trail
    
    Enhanced features:
    - Distributed locking for state transitions
    - Idempotency guards on start/resume operations
    - Timeout enforcement with automatic compensation
    - Circuit breaker for adapter resilience
    - Retry logic with exponential backoff
    - Distributed tracing with correlation_id
    - Ordered compensation (LIFO)
    """
    
    def __init__(
        self,
        db_connection_string: str,
        adapter_registry: Dict[str, Any],
        logger_instance: Optional[logging.Logger] = None,
        async_mode: bool = True,  # kept for backward compat; always True
        saga_update_handler: Optional[Callable[[Dict[str, Any]], Any]] = None,
        redis_url: Optional[str] = None,
        db: Optional[AsyncDatabaseProtocol] = None,
        db_factory: Optional[Callable[[], Awaitable[AsyncDatabaseProtocol]]] = None,
    ):
        """
        Initialize orchestrator (async-only).
        
        Args:
            db_connection_string: PostgreSQL connection string
            adapter_registry: Dict of adapter_type → adapter instance
            logger_instance: Logger for trace/debug
            async_mode: **Deprecated** — always True.  Passing False raises NotImplementedError.
            saga_update_handler: Callback for saga state updates
            redis_url: Redis URL for distributed locks and idempotency
            db: Optional pre-initialised async DB connection
            db_factory: Optional callable returning an async DB connection
        """
        if not async_mode:
            raise NotImplementedError(
                "Sync mode was removed in Phase 3.  Use async_mode=True (the default)."
            )
        self.db_url = db_connection_string
        self.adapters = adapter_registry
        self.logger = logger_instance or logger
        self.async_mode = True  # always async
        self.db = db  # Lazy initialized unless injected
        self._db_injected = db is not None
        self._db_factory = db_factory
        self.saga_update_handler = saga_update_handler
        self._testing_mode = bool(os.getenv("PYTEST_CURRENT_TEST"))
        
        # Distributed lock manager
        self.redis_client = None
        self.redis_url = redis_url
        self.lock_manager = DistributedLock(
            None,
            None,
            fail_open=self._testing_mode,
            db_url=self.db_url,
            async_mode=async_mode,
        )  # Initialized in init_async
        
        # Circuit breakers per adapter (will be initialized with Redis in init_async)
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        
        # Retry configuration
        self.retry_config = RetryConfig(max_attempts=3, initial_delay=1.0, max_delay=30.0)
        
        # Idempotency tracking with TTL cache (1 hour TTL, max 10k entries)
        self.idempotency_ttl_seconds = int(os.getenv("SAGA_IDEMPOTENCY_TTL_SECONDS", "3600"))
        self.idempotency_cache = TTLCache(ttl_seconds=self.idempotency_ttl_seconds, max_size=10000)

        # Adapter call timeout (seconds)
        self.adapter_timeout_seconds = float(os.getenv("SAGA_ADAPTER_TIMEOUT_SECONDS", "30"))
        
        # Production monitoring and protection features
        self.metrics_collector = SagaMetricsCollector()
        self.prom_metrics = PrometheusSagaMetrics()
        self.telemetry_collector = SagaTelemetryCollector(
            service_name="saga-orchestrator",
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        )
        self.rate_limiter = RateLimiter(RateLimitPolicy())
        self.dlq = DeadLetterQueue(max_size=10000)
        self._active_traces: Dict[str, Dict[str, Any]] = {}
        self._active_sagas: set[str] = set()
        self._saga_start_times: Dict[str, float] = {}
        # Maximum age (seconds) before an active saga entry is considered stale.
        self._saga_stale_threshold = float(os.getenv("SAGA_STALE_THRESHOLD_SECONDS", "3600"))

    # ------------------------------------------------------------------
    # Periodic housekeeping
    # ------------------------------------------------------------------

    def sweep_stale_sagas(self) -> int:
        """Remove saga tracking entries older than *_saga_stale_threshold*.

        Call this periodically (e.g. from a scheduler) to prevent unbounded
        growth of ``_active_sagas`` / ``_saga_start_times`` when a saga never
        reaches a terminal state.

        Returns the number of entries evicted.
        """
        now = time.perf_counter()
        stale_ids = [
            sid for sid, start in self._saga_start_times.items()
            if (now - start) > self._saga_stale_threshold
        ]
        for sid in stale_ids:
            self._active_sagas.discard(sid)
            self._saga_start_times.pop(sid, None)
            self._active_traces.pop(sid, None)
            self.logger.warning("Evicted stale saga tracking entry: %s", sid)
        if stale_ids:
            self.prom_metrics.set_active_sagas_count(len(self._active_sagas))
        return len(stale_ids)

    async def init_async(self):
        """Initialize Redis client and lock manager."""
        if self.db is None:
            if self._db_factory is None:
                if not self._testing_mode:
                    raise RuntimeError("SagaOrchestrator requires an AsyncDatabaseProtocol")
                return
            self.db = await self._db_factory()
        self.logger.info("🔌 SagaOrchestrator using injected DB adapter")
        await self._ensure_persistent_dlq_storage()
        
        # Initialize Redis for distributed locks and circuit breaker persistence
        if self.redis_url and redis:
            try:
                self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
                await self.redis_client.ping()
                self.lock_manager = DistributedLock(
                    self.redis_client,
                    self.db,
                    db_url=self.db_url,
                    async_mode=True,
                    fail_open=False,
                )
                self.logger.info("🔌 SagaOrchestrator Redis initialized for distributed locks")
            except Exception as e:
                self.logger.warning(f"Redis initialization failed, using DB-only locks: {e}")
                self.lock_manager = DistributedLock(
                    None,
                    self.db,
                    db_url=self.db_url,
                    async_mode=True,
                    fail_open=False,
                )
        else:
            self.lock_manager = DistributedLock(
                None,
                self.db,
                db_url=self.db_url,
                async_mode=True,
                fail_open=False,
            )
        
        # Initialize circuit breakers with Redis persistence
        for adapter_name in self.adapters.keys():
            circuit_breaker = CircuitBreaker(
                CircuitBreakerConfig(),
                adapter_name=adapter_name,
                redis_client=self.redis_client,
                metrics=self.prom_metrics,
            )
            # Load persisted state
            await circuit_breaker.load_state()
            self.circuit_breakers[adapter_name] = circuit_breaker

    async def _ensure_persistent_dlq_storage(self) -> None:
        if self.db is None:
            return
        try:
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS saga_dlq_messages (
                    id BIGSERIAL PRIMARY KEY,
                    saga_id TEXT NOT NULL,
                    action_id TEXT,
                    correlation_id TEXT,
                    flow_name TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    last_successful_step TEXT,
                    failed_step TEXT,
                    saga_state JSONB NOT NULL DEFAULT '{}'::jsonb,
                    attempted_compensation_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    saga_duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_retry_at TIMESTAMPTZ,
                    next_retry_at TIMESTAMPTZ,
                    client_id TEXT,
                    user_id TEXT,
                    tags JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            await self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_saga_dlq_messages_created_at ON saga_dlq_messages(created_at DESC)"
            )
            await self.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_saga_dlq_messages_saga_id ON saga_dlq_messages(saga_id)"
            )
        except Exception as e:
            self.logger.warning(f"Failed to initialize persistent DLQ storage: {e}")

    async def _persist_dlq_message(self, message: DLQMessage) -> None:
        if self.db is None:
            return
        try:
            await self.db.execute(
                """
                INSERT INTO saga_dlq_messages(
                    saga_id, action_id, correlation_id, flow_name, message_type,
                    error_message, error_type, last_successful_step, failed_step,
                    saga_state, attempted_compensation_steps, created_at,
                    saga_duration_ms, retry_count, last_retry_at, next_retry_at,
                    client_id, user_id, tags
                )
                VALUES(
                    $1, $2, $3, $4, $5,
                    $6, $7, $8, $9,
                    $10::jsonb, $11::jsonb, $12,
                    $13, $14, $15, $16,
                    $17, $18, $19::jsonb
                )
                """,
                message.saga_id,
                message.action_id,
                message.correlation_id,
                message.flow_name,
                message.message_type.value,
                message.error_message,
                message.error_type,
                message.last_successful_step,
                message.failed_step,
                json.dumps(message.saga_state or {}, default=str),
                json.dumps(message.attempted_compensation_steps or [], default=str),
                message.created_at,
                float(message.saga_duration_ms or 0.0),
                int(message.retry_count or 0),
                message.last_retry_at,
                message.next_retry_at,
                message.client_id,
                message.user_id,
                json.dumps(message.tags or {}, default=str),
            )
        except Exception as e:
            self.logger.warning(f"Failed to persist DLQ message for saga {message.saga_id}: {e}")

    @staticmethod
    def _normalize_dlq_row(row: Any) -> Dict[str, Any]:
        data = dict(row)
        for key in ("saga_state", "attempted_compensation_steps", "tags"):
            value = data.get(key)
            if isinstance(value, str):
                try:
                    data[key] = json.loads(value)
                except Exception:
                    logging.debug("Suppressed exception", exc_info=True)
        return data

    async def list_persistent_dlq_messages(
        self,
        *,
        limit: int = 100,
        saga_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if self.db is None:
            return []

        safe_limit = max(1, min(limit, 500))

        if saga_id:
            rows = await self.db.fetch(
                """
                SELECT *
                FROM saga_dlq_messages
                WHERE saga_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                saga_id,
                safe_limit,
            )
        else:
            rows = await self.db.fetch(
                """
                SELECT *
                FROM saga_dlq_messages
                ORDER BY created_at DESC
                LIMIT $1
                """,
                safe_limit,
            )

        return [self._normalize_dlq_row(row) for row in rows]

    async def get_latest_persistent_dlq_message(self, saga_id: str) -> Optional[Dict[str, Any]]:
        messages = await self.list_persistent_dlq_messages(limit=1, saga_id=saga_id)
        return messages[0] if messages else None

    async def retry_persistent_dlq_message(
        self,
        saga_id: str,
        *,
        retry_delay_seconds: int = 0,
    ) -> Optional[Dict[str, Any]]:
        if self.db is None:
            return None

        retry_delay_seconds = max(0, int(retry_delay_seconds))
        now = datetime.now(timezone.utc)
        next_retry_at = now + timedelta(seconds=retry_delay_seconds)

        row = await self.db.fetchrow(
            """
            UPDATE saga_dlq_messages
            SET retry_count = retry_count + 1,
                last_retry_at = $2,
                next_retry_at = $3
            WHERE id = (
                SELECT id
                FROM saga_dlq_messages
                WHERE saga_id = $1
                ORDER BY created_at DESC
                LIMIT 1
            )
            RETURNING *
            """,
            saga_id,
            now,
            next_retry_at,
        )
        if not row:
            return None
        return self._normalize_dlq_row(row)

    async def remove_persistent_dlq_message(self, saga_id: str) -> int:
        if self.db is None:
            return 0
        result = await self.db.execute(
            """
            DELETE FROM saga_dlq_messages
            WHERE id IN (
                SELECT id
                FROM saga_dlq_messages
                WHERE saga_id = $1
                ORDER BY created_at DESC
                LIMIT 1
            )
            """,
            saga_id,
        )
        if isinstance(result, str) and result.startswith("DELETE"):
            parts = result.split()
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
        return 0

    async def list_persistent_dlq_retry_candidates(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        if self.db is None:
            return []

        safe_limit = max(1, min(limit, 500))
        rows = await self.db.fetch(
            """
            SELECT *
            FROM saga_dlq_messages
            WHERE next_retry_at IS NOT NULL
              AND next_retry_at <= NOW()
            ORDER BY next_retry_at ASC, created_at ASC
            LIMIT $1
            """,
            safe_limit,
        )
        return [self._normalize_dlq_row(row) for row in rows]

    async def bulk_triage_persistent_dlq_messages(
        self,
        saga_ids: List[str],
        *,
        triage_status: str,
        note: Optional[str] = None,
        retry_delay_seconds: Optional[int] = None,
    ) -> int:
        if self.db is None:
            return 0

        normalized_saga_ids = [str(s).strip() for s in saga_ids if str(s).strip()]
        if not normalized_saga_ids:
            return 0

        safe_status = str(triage_status or "pending").strip().lower() or "pending"
        tags_payload: Dict[str, Any] = {
            "triage_status": safe_status,
            "triaged_at": datetime.now(timezone.utc).isoformat(),
        }
        if note:
            tags_payload["triage_note"] = str(note)

        if retry_delay_seconds is not None:
            safe_delay = max(0, int(retry_delay_seconds))
            next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=safe_delay)
            result = await self.db.execute(
                """
                UPDATE saga_dlq_messages
                SET tags = COALESCE(tags, '{}'::jsonb) || $2::jsonb,
                    next_retry_at = $3
                WHERE saga_id = ANY($1)
                """,
                normalized_saga_ids,
                json.dumps(tags_payload, default=str),
                next_retry_at,
            )
        else:
            result = await self.db.execute(
                """
                UPDATE saga_dlq_messages
                SET tags = COALESCE(tags, '{}'::jsonb) || $2::jsonb
                WHERE saga_id = ANY($1)
                """,
                normalized_saga_ids,
                json.dumps(tags_payload, default=str),
            )

        if isinstance(result, str) and result.startswith("UPDATE"):
            parts = result.split()
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
        return 0

    async def purge_persistent_dlq_messages(
        self,
        *,
        older_than_days: int = 30,
        limit: int = 1000,
    ) -> int:
        if self.db is None:
            return 0

        safe_days = max(1, int(older_than_days))
        safe_limit = max(1, min(int(limit), 5000))

        result = await self.db.execute(
            """
            DELETE FROM saga_dlq_messages
            WHERE id IN (
                SELECT id
                FROM saga_dlq_messages
                WHERE created_at < NOW() - make_interval(days => $1)
                ORDER BY created_at ASC
                LIMIT $2
            )
            """,
            safe_days,
            safe_limit,
        )

        if isinstance(result, str) and result.startswith("DELETE"):
            parts = result.split()
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
        return 0

    async def replay_saga_from_dlq(self, saga_id: str) -> Dict[str, Any]:
        saga = await self._get_saga(saga_id)
        if not saga:
            raise ValueError(f"Saga {saga_id} not found")

        if saga.get("state") == SagaState.SUCCEEDED.value:
            return {
                "status": "skipped",
                "reason": "already_succeeded",
                "saga_id": saga_id,
            }

        payload = saga.get("payload") if isinstance(saga.get("payload"), dict) else {}
        correlation_id = str(saga.get("correlation_id") or payload.get("correlation_id") or "")

        await self._update_saga_state(
            saga_id,
            SagaState.IN_PROGRESS.value,
            steps=saga.get("steps", []) or [],
            result={
                "replay_requested": True,
                "replay_requested_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        await self._run_saga(
            saga_id=saga_id,
            action_id=str(saga.get("action_id") or ""),
            saga_type=str(saga.get("saga_type") or ""),
            payload=payload,
            user_id=saga.get("user_id"),
            correlation_id=correlation_id or None,
            trace_id=None,
            saga_version=saga.get("saga_version"),
        )

        return {
            "status": "replayed",
            "saga_id": saga_id,
            "saga_type": saga.get("saga_type"),
            "correlation_id": correlation_id,
        }
    
    async def close_async(self):
        """Close async connection and Redis client."""
        if self.db and not self._db_injected:
            await self.db.close()
        if self.redis_client:
            await self.redis_client.close()

    async def _run_step_compensation(
        self,
        executed_steps: List[tuple[SagaStepDefinition, SagaStepResult]],
        error: Exception,
    ) -> None:
        for step_def, step_result in reversed(executed_steps):
            if not step_def.compensate:
                continue
            action = CompensationAction(
                step_name=step_def.name,
                reason=str(error),
                meta=step_result.meta if step_result else None,
            )
            try:
                await step_def.compensate(action)
            except Exception as comp_error:
                self.logger.warning(
                    f"Compensation failed for step '{step_def.name}': {comp_error}"
                )

    async def execute_step_plan(
        self,
        *,
        saga_id: str,
        saga_type: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        step_plan: List[SagaStepDefinition],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result_payload: Dict[str, Any] = {}
        executed_steps: List[tuple[SagaStepDefinition, SagaStepResult]] = []

        try:
            for step_def in step_plan:
                step_record = SagaStepRecord(
                    name=step_def.name,
                    status=StepStatus.IN_PROGRESS.value,
                    adapter_type=step_def.adapter_type,
                    compensatable=bool(step_def.compensate),
                )
                steps.append(step_record.to_dict())

                step_result = await step_def.execute()
                if step_result is None:
                    step_result = SagaStepResult()

                steps[-1]["status"] = StepStatus.SUCCEEDED.value
                if step_result.meta is not None:
                    steps[-1]["meta"] = step_result.meta

                if step_result.result:
                    result_payload.update(step_result.result)

                executed_steps.append((step_def, step_result))

                if step_result.pause:
                    pending_step = SagaStepRecord(
                        name="await_user_confirm",
                        status=StepStatus.PENDING.value,
                    )
                    steps.append(pending_step.to_dict())
                    await self._update_saga_state(
                        saga_id,
                        SagaState.WAITING_CONFIRM.value,
                        steps=steps,
                        result=result_payload,
                    )
                    return {"status": "paused", "result": result_payload}

            await self._update_saga_state(
                saga_id,
                SagaState.SUCCEEDED.value,
                steps=steps,
                result=result_payload,
            )
            return {"status": "succeeded", "result": result_payload}

        except Exception as exc:
            if steps:
                steps[-1]["status"] = StepStatus.FAILED.value
                steps[-1]["error"] = str(exc)
            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(exc)},
            )
            await self._run_step_compensation(executed_steps, exc)

            if saga_type == "llm_pipeline":
                try:
                    llm_snapshot = self._extract_llm_dlq_snapshot(
                        steps=steps,
                        result_payload=result_payload,
                        error=exc,
                    )
                    dlq_message = DLQMessage(
                        saga_id=saga_id,
                        action_id=str(payload.get("action_id") or ""),
                        correlation_id=str(correlation_id or payload.get("correlation_id") or ""),
                        flow_name=saga_type,
                        message_type=DLQMessageType.PERMANENT_FAILURE,
                        error_message=str(exc),
                        error_type=type(exc).__name__,
                        last_successful_step=self._get_last_successful_step_name(steps),
                        failed_step=steps[-1].get("name") if steps else "unknown",
                        saga_state={
                            "steps": steps,
                            **llm_snapshot,
                        },
                        tags={
                            "saga_type": "llm_pipeline",
                            "stop_reason": str(llm_snapshot.get("stop_reason") or "internal_error"),
                        },
                    )
                    self.dlq.add_message(dlq_message)
                    await self._persist_dlq_message(dlq_message)
                except Exception as dlq_error:
                    self.logger.warning(f"Failed to enqueue llm_pipeline DLQ message: {dlq_error}")

            return {"status": "failed", "error": str(exc)}

    @staticmethod
    def _get_last_successful_step_name(steps: List[Dict[str, Any]]) -> str:
        return next(
            (step.get("name") for step in reversed(steps) if step.get("status") == StepStatus.SUCCEEDED.value),
            "",
        )

    def _extract_llm_dlq_snapshot(
        self,
        *,
        steps: List[Dict[str, Any]],
        result_payload: Dict[str, Any],
        error: Exception,
    ) -> Dict[str, Any]:
        budget_snapshot: Dict[str, Any] = {}
        policy_snapshot: Dict[str, Any] = {}
        model_snapshot: Dict[str, Any] = {}

        for step in reversed(steps):
            meta = step.get("meta") if isinstance(step.get("meta"), dict) else {}
            if not budget_snapshot and isinstance(meta.get("budget"), dict):
                budget_snapshot = meta.get("budget") or {}
            if not policy_snapshot and isinstance(meta.get("policy"), dict):
                policy_snapshot = meta.get("policy") or {}
            if not model_snapshot and isinstance(meta.get("model"), dict):
                model_snapshot = meta.get("model") or {}
            if budget_snapshot and policy_snapshot and model_snapshot:
                break

        stop_reason = str(error)
        if isinstance(result_payload.get("stop_reason"), str) and result_payload.get("stop_reason"):
            stop_reason = str(result_payload.get("stop_reason"))

        return {
            "pipeline_name": "llm_pipeline",
            "pipeline_version": "v1",
            "stop_reason": stop_reason,
            "budget_snapshot": budget_snapshot,
            "policy_snapshot": policy_snapshot,
            "model_snapshot": model_snapshot,
            "validator_report_ref": result_payload.get("validation_report"),
            "best_output_ref": result_payload.get("best_output"),
        }
    
    # =========================================================================
    # Circuit Breaker Helper
    # =========================================================================
    
    def _get_circuit_breaker(self, adapter_name: str) -> CircuitBreaker:
        """Get or create circuit breaker for adapter."""
        if adapter_name not in self.circuit_breakers:
            self.circuit_breakers[adapter_name] = CircuitBreaker(
                CircuitBreakerConfig(),
                adapter_name=adapter_name,
                redis_client=self.redis_client,
                metrics=self.prom_metrics,
            )
        return self.circuit_breakers[adapter_name]

    # =========================================================================
    # Trace Context Helpers
    # =========================================================================

    def _build_trace_context(
        self,
        *,
        saga_id: str,
        correlation_id: str,
        trace_id: str,
        action_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "trace_id": trace_id,
            "correlation_id": correlation_id,
            "saga_id": saga_id,
            "action_id": action_id,
            "user_id": user_id,
        }

    def _ensure_trace_context(
        self,
        *,
        saga_id: str,
        saga_type: Optional[str],
        action_id: Optional[str],
        user_id: Optional[str],
        correlation_id: Optional[str],
        trace_id: Optional[str],
    ) -> Dict[str, Any]:
        existing = self._active_traces.get(saga_id)
        if existing:
            return existing

        resolved_trace_id = trace_id or self.telemetry_collector.create_trace_id()
        resolved_correlation_id = correlation_id or resolved_trace_id

        root_span_id = self.telemetry_collector.start_saga_trace(
            saga_id,
            resolved_correlation_id,
            saga_type or "unknown",
            trace_id=resolved_trace_id,
            action_id=action_id,
            user_id=user_id,
        )

        trace_context = {
            "trace_id": resolved_trace_id,
            "correlation_id": resolved_correlation_id,
            "root_span_id": root_span_id,
        }
        self._active_traces[saga_id] = trace_context
        return trace_context

    def _resolve_trace_context_from_steps(self, steps: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        if not steps:
            return None
        for step in reversed(steps):
            trace_id = step.get("trace_id")
            correlation_id = step.get("correlation_id")
            if trace_id or correlation_id:
                return {
                    "trace_id": trace_id or correlation_id,
                    "correlation_id": correlation_id or trace_id,
                    "root_span_id": None,
                }
        return None

    def _safe_payload_size(self, payload: Any) -> int:
        try:
            return len(json.dumps(payload))
        except Exception:
            return 0

    async def _call_adapter_method(
        self,
        adapter: Any,
        method_name: str,
        *args: Any,
        trace_context: Optional[Dict[str, Any]] = None,
        adapter_name: Optional[str] = None,
        operation_name: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        method = getattr(adapter, method_name, None)
        if not method:
            raise ValueError(f"Adapter does not have method: {method_name}")

        kwargs: Dict[str, Any] = {}
        try:
            signature = inspect.signature(method)
            params = signature.parameters
            if trace_context:
                if "trace_context" in params:
                    kwargs["trace_context"] = trace_context
                if "trace_id" in params:
                    kwargs["trace_id"] = trace_context.get("trace_id")
                if "correlation_id" in params:
                    kwargs["correlation_id"] = trace_context.get("correlation_id")
        except (TypeError, ValueError):
            pass

        effective_timeout = timeout if timeout is not None else self.adapter_timeout_seconds

        adapter_label = adapter_name or getattr(adapter, "name", None) or adapter.__class__.__name__
        operation_label = operation_name or method_name
        start_time = time.perf_counter()
        status = "success"

        try:
            if inspect.iscoroutinefunction(method):
                coro = method(*args, **kwargs)
                if effective_timeout:
                    return await asyncio.wait_for(coro, timeout=effective_timeout)
                return await coro

            if effective_timeout:
                result = await asyncio.wait_for(
                    asyncio.to_thread(method, *args, **kwargs),
                    timeout=effective_timeout,
                )
            else:
                result = method(*args, **kwargs)

            if asyncio.iscoroutine(result):
                if effective_timeout:
                    return await asyncio.wait_for(result, timeout=effective_timeout)
                return await result
            return result
        except Exception:
            status = "error"
            raise
        finally:
            duration = time.perf_counter() - start_time
            if adapter_label:
                self.prom_metrics.observe_adapter_latency(adapter_label, operation_label, duration)
                self.prom_metrics.record_adapter_call(adapter_label, operation_label, status)
    
    # =========================================================================
    # Idempotency Guards
    # =========================================================================
    
    def _get_idempotency_key(self, saga_id: str, operation: str) -> str:
        """Generate idempotency key for saga operation."""
        return f"{saga_id}:{operation}"
    
    async def _check_idempotency(self, saga_id: str, operation: str) -> Optional[Any]:
        """Check if operation was already executed (cache → Redis → DB)."""
        key = self._get_idempotency_key(saga_id, operation)

        cached = await self.idempotency_cache.get(key)
        if cached is not None:
            return cached

        if self.db is None:
            if self._testing_mode:
                return None
            self.logger.warning("Idempotency DB unavailable; skipping DB lookup")
            return None

        try:
            query = """
            SELECT result
            FROM saga_idempotency
            WHERE key = $1
              AND (expires_at IS NULL OR expires_at > NOW())
            """
            row = await self.db.fetchrow(query, key)
            if row:
                value = row["result"]
                await self.idempotency_cache.set(key, value)
                if self.redis_client:
                    try:
                        await self.redis_client.setex(
                            f"saga:idempotency:{key}",
                            self.idempotency_ttl_seconds,
                            json.dumps(value, default=str),
                        )
                    except Exception as e:
                        self.logger.warning(f"Failed to write idempotency to Redis: {e}")
                return value
        except Exception as e:
            self.logger.warning(f"Failed to read idempotency from DB: {e}")

        return None
    
    async def _record_idempotency(self, saga_id: str, operation: str, result: Any):
        """Record operation result for idempotency (cache + Redis/DB best-effort)."""
        key = self._get_idempotency_key(saga_id, operation)
        serialized = json.dumps(result, default=str)

        if self.db is None:
            if not self._testing_mode:
                self.logger.warning("Idempotency DB unavailable; skipping DB write")
            await self.idempotency_cache.set(key, result)
            if self.redis_client:
                try:
                    await self.redis_client.setex(
                        f"saga:idempotency:{key}",
                        self.idempotency_ttl_seconds,
                        serialized,
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to write idempotency to Redis: {e}")
            return

        try:
            query = """
            INSERT INTO saga_idempotency (key, result, created_at, expires_at)
            VALUES ($1, $2, NOW(), NOW() + INTERVAL '%s seconds')
            ON CONFLICT (key) DO UPDATE
            SET result = EXCLUDED.result,
                created_at = NOW(),
                expires_at = EXCLUDED.expires_at
            """ % self.idempotency_ttl_seconds
            await self.db.execute(query, key, serialized)
        except Exception as e:
            self.logger.warning(f"Failed to write idempotency to DB: {e}")
            raise

        await self.idempotency_cache.set(key, result)

        if self.redis_client:
            try:
                await self.redis_client.setex(
                    f"saga:idempotency:{key}",
                    self.idempotency_ttl_seconds,
                    serialized,
                )
            except Exception as e:
                self.logger.warning(f"Failed to write idempotency to Redis: {e}")

    def _resolve_saga_version(self, saga_type: str, saga_version: Optional[str] = None) -> str:
        """Resolve saga version for a given saga_type."""
        if saga_version:
            return saga_version
        registry = SAGA_VERSION_REGISTRY.get(saga_type)
        if registry:
            return registry.get("current", "v1")
        return "v1"

    def _get_saga_handler(
        self,
        saga_type: str,
        saga_version: str,
        *,
        resume: bool = False,
    ) -> Optional[Callable]:
        """Get saga handler for a specific saga_type and version."""
        registry = SAGA_VERSION_REGISTRY.get(saga_type, {})
        handler_map = registry.get("resume_handlers" if resume else "handlers", {})
        handler_spec = handler_map.get(saga_version)
        if not handler_spec:
            return None
        if isinstance(handler_spec, str):
            return getattr(self, handler_spec, None)
        if isinstance(handler_spec, type) and issubclass(handler_spec, BaseSaga):
            flow = handler_spec(self)
            if resume:
                if handler_spec.resume is BaseSaga.resume:
                    return None
                return flow.resume
            if handler_spec.run is BaseSaga.run:
                return None
            return flow.run
        if callable(handler_spec):
            return handler_spec
        return None

    def _infer_saga_type_from_steps(self, steps: List[Dict[str, Any]]) -> Optional[str]:
        step_names = {step.get("name") for step in steps}
        if "reserve_slot" in step_names:
            return "booking_flow"
        if "create_event" in step_names:
            return "calendar_flow"
        return None

    def _insert_saga(
        self,
        *,
        saga_id: str,
        action_id: str,
        user_id: Optional[str],
        saga_type: str,
        saga_version: Optional[str],
        state: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        expires_at_seconds: int,
        correlation_id: str,
    ) -> None:
        return None
    
    # =========================================================================
    # Timeout Enforcement
    # =========================================================================
    
    async def _check_saga_timeout(self, saga_id: str) -> bool:
        """Check if saga has exceeded timeout and trigger compensation if needed."""
        saga = await self._get_saga(saga_id)
        if not saga:
            return False
        
        expires_at = saga.get("expires_at")
        if not expires_at:
            return False
        
        now = datetime.now(timezone.utc)
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        
        if now > expires_at:
            self.logger.warning(f"⏰ Saga {saga_id} timed out, triggering compensation")
            
            # Trigger compensation
            steps = saga.get("steps", [])

            trace_context = (
                self._active_traces.get(saga_id)
                or self._resolve_trace_context_from_steps(steps)
                or self._ensure_trace_context(
                    saga_id=saga_id,
                    saga_type=saga.get("saga_type"),
                    action_id=saga.get("action_id"),
                    user_id=saga.get("user_id"),
                    correlation_id=saga.get("correlation_id"),
                    trace_id=None,
                )
            )
            await self._compensate_saga(
                saga_id,
                saga,
                steps,
                Exception(f"Saga timeout after {expires_at}"),
            )
            return True
        
        return False

    async def _attempt_compensation(
        self,
        saga_id: str,
        saga_type: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        error: Exception,
    ) -> None:
        if not any(
            s.get("status") == StepStatus.SUCCEEDED.value
            and s.get("compensatable", False)
            for s in steps
        ):
            return
        try:
            await self._compensate_saga(
                saga_id,
                {"payload": payload, "saga_type": saga_type},
                steps,
                error,
            )
        except Exception as comp_error:
            self.logger.warning(f"Compensation failed after saga error: {comp_error}")
            try:
                last_success = next(
                    (s.get("name") for s in reversed(steps) if s.get("status") == StepStatus.SUCCEEDED.value),
                    "",
                )
                extra_saga_state: Dict[str, Any] = {"steps": steps}
                if saga_type == "llm_pipeline":
                    extra_saga_state.update(
                        self._extract_llm_dlq_snapshot(
                            steps=steps,
                            result_payload=payload if isinstance(payload, dict) else {},
                            error=comp_error,
                        )
                    )
                dlq_message = DLQMessage(
                    saga_id=saga_id,
                    action_id=payload.get("action_id", ""),
                    correlation_id=payload.get("correlation_id", ""),
                    flow_name=saga_type,
                    message_type=DLQMessageType.COMPENSATION_FAILED,
                    error_message=str(comp_error),
                    error_type=type(comp_error).__name__,
                    last_successful_step=last_success,
                    failed_step="compensation",
                    saga_state=extra_saga_state,
                    tags={
                        "saga_type": str(saga_type),
                        "stop_reason": str(extra_saga_state.get("stop_reason") or "compensation_failed"),
                    },
                )
                self.dlq.add_message(dlq_message)
                await self._persist_dlq_message(dlq_message)
            except Exception as dlq_error:
                self.logger.warning(f"Failed to enqueue DLQ message: {dlq_error}")

    async def archive_waiting_confirm_sagas(self, ttl_seconds: Optional[int] = None, batch_size: int = 500) -> int:
        """Archive sagas stuck in WAITING_CONFIRM beyond TTL."""
        ttl_seconds = ttl_seconds if ttl_seconds is not None else WAITING_CONFIRM_TTL_SECONDS
        if ttl_seconds <= 0:
            return 0

        if self.db is None:
            if self._testing_mode:
                return 0
            raise RuntimeError("Saga DB not initialized")

        query = """
        UPDATE sagas
        SET state = $1,
            result = COALESCE(result, '{}'::jsonb) || $2::jsonb,
            updated_at = NOW()
        WHERE saga_id IN (
            SELECT saga_id
            FROM sagas
            WHERE state = $3
              AND updated_at < NOW() - INTERVAL '%s seconds'
            LIMIT $4
        )
        RETURNING saga_id
        """ % ttl_seconds

        archive_payload = json.dumps({
            "archived_reason": "waiting_confirm_ttl",
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": ttl_seconds,
        })

        try:
            rows = await self.db.fetch(
                query,
                SagaState.ARCHIVED.value,
                archive_payload,
                SagaState.WAITING_CONFIRM.value,
                batch_size,
            )
            return len(rows)
        except Exception as exc:
            self.logger.warning(f"Failed to archive waiting_confirm sagas: {exc}")
            return 0
    
    # =========================================================================
    # Core Saga Lifecycle (Enhanced)
    # =========================================================================
    
    async def start_saga(
        self,
        action_id: str,
        saga_type: str,
        payload: Dict[str, Any],
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        saga_version: Optional[str] = None,
        retry_count: int = 0,
        max_retries: int = 5,
    ) -> str:
        """
        Create and start a new saga.
        
        Args:
            action_id: ID of the action triggering saga
            saga_type: Type of saga (e.g., "booking_flow")
            payload: Input parameters
            user_id: User ID for audit
            correlation_id: Distributed tracing correlation ID
            trace_id: OpenTelemetry trace ID
            saga_version: Optional saga definition version (defaults to current)
            
        Returns:
            saga_id (UUID string)
        """
        # Generate saga_id (deterministic based on action_id for idempotency)
        saga_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"saga:{action_id}"))
        
        # Idempotency check
        cached = await self._check_idempotency(saga_id, "start")
        if cached:
            self.logger.info(f"🔄 Idempotent saga start detected: {saga_id}")
            return cached
        
        # Acquire distributed lock
        lock_acquired = await self.lock_manager.acquire(saga_id, "state")
        if not lock_acquired:
            self.logger.warning(f"⏳ Failed to acquire lock for saga start: {saga_id}")
            # Check if saga already exists
            existing = await self._get_saga(saga_id)
            if existing:
                await self._record_idempotency(saga_id, "start", saga_id)
                return saga_id
            if retry_count >= max_retries:
                raise TimeoutError(f"Failed to acquire lock for saga start: {saga_id}")
            # Wait and retry
            await asyncio.sleep(1)
            return await self.start_saga(
                action_id,
                saga_type,
                payload,
                user_id,
                correlation_id,
                trace_id,
                saga_version,
                retry_count + 1,
                max_retries,
            )
        
        inserted = False
        resolved_version = None
        steps = []
        trace_context = None

        try:
            # Insert saga record
            # Use per-saga-type timeout
            timeout = SAGA_TIMEOUTS.get(saga_type, timedelta(days=7))
            timeout_seconds = int(timeout.total_seconds())

            resolved_version = self._resolve_saga_version(
                saga_type,
                saga_version or payload.get("saga_version") if isinstance(payload, dict) else saga_version,
            )

            query = f"""
            INSERT INTO sagas (saga_id, action_id, user_id, saga_type, saga_version, state, payload, steps, expires_at, correlation_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW() + INTERVAL '{timeout_seconds} seconds', $9)
            ON CONFLICT (saga_id) DO NOTHING
            """

            correlation_id = correlation_id or str(uuid.uuid4())
            trace_context = self._ensure_trace_context(
                saga_id=saga_id,
                saga_type=saga_type,
                action_id=action_id,
                user_id=user_id,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

            hook_result = self._insert_saga(
                saga_id=saga_id,
                action_id=action_id,
                user_id=user_id,
                saga_type=saga_type,
                saga_version=resolved_version,
                state=SagaState.PENDING.value,
                payload=payload,
                steps=steps,
                expires_at_seconds=timeout_seconds,
                correlation_id=correlation_id,
            )
            if inspect.iscoroutine(hook_result):
                await hook_result

            if self.db is None:
                if not self._testing_mode:
                    raise RuntimeError("Saga DB not initialized")
                inserted = True
            else:
                result = await self.db.execute(
                    query,
                    saga_id,
                    action_id,
                    user_id,
                    saga_type,
                    resolved_version,
                    SagaState.PENDING.value,
                    json.dumps(payload),
                    json.dumps([s.to_dict() if isinstance(s, SagaStepRecord) else s for s in steps]),
                    correlation_id,
                )
                inserted = "INSERT 0 1" in result

            self.logger.info(
                f"📝 Saga created: {saga_id} ({saga_type}@{resolved_version}) "
                f"[correlation: {correlation_id}] [trace: {trace_context.get('trace_id')}]"
            )

            # Record idempotency
            await self._record_idempotency(saga_id, "start", saga_id)

            # Atomic state transition under lock (PENDING -> IN_PROGRESS)
            if inserted and self.db is not None:
                cas_result = await self.db.execute(
                    """
                    UPDATE sagas
                    SET state = $1, updated_at = NOW()
                    WHERE saga_id = $2 AND state = $3
                    """,
                    SagaState.IN_PROGRESS.value,
                    saga_id,
                    SagaState.PENDING.value,
                )
                if "UPDATE 0" in cas_result:
                    self.logger.info(f"Saga {saga_id} already transitioned by another process")
                    inserted = False

        except Exception as e:
            self.logger.error(f"❌ Failed to start saga: {e}")
            raise
        finally:
            await self.lock_manager.release(saga_id, "state")

        if inserted:
            self.prom_metrics.record_saga_started()
            self._active_sagas.add(saga_id)
            self._saga_start_times[saga_id] = time.perf_counter()
            self.prom_metrics.set_active_sagas_count(len(self._active_sagas))
            # Kick off saga execution outside the lock
            await self._run_saga(
                saga_id,
                action_id,
                saga_type,
                payload,
                user_id,
                correlation_id,
                trace_context.get("trace_id") if trace_context else trace_id,
                resolved_version,
            )
        else:
            self.logger.info(f"↩️  Saga already exists, skipping run: {saga_id}")

        return saga_id
    
    async def _run_saga(
        self,
        saga_id: str,
        action_id: str,
        saga_type: str,
        payload: Dict[str, Any],
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        saga_version: Optional[str] = None,
    ):
        """
        Execute saga steps (background task).
        
        Runs through initial steps, then pauses at confirmation point.
        """
        try:
            # Check timeout before execution
            if await self._check_saga_timeout(saga_id):
                return
            
            # Fetch saga
            saga = await self._get_saga(saga_id)
            if not saga:
                raise ValueError(f"Saga {saga_id} not found")
            
            steps = saga.get("steps", [])
            trace_context = (
                self._active_traces.get(saga_id)
                or self._resolve_trace_context_from_steps(steps)
                or self._ensure_trace_context(
                    saga_id=saga_id,
                    saga_type=saga_type,
                    action_id=action_id,
                    user_id=user_id,
                    correlation_id=correlation_id or saga.get("correlation_id"),
                    trace_id=trace_id,
                )
            )

            # If saga is already waiting for confirmation or finished, avoid re-running initial steps
            current_state = saga.get("state")
            if current_state == SagaState.WAITING_CONFIRM.value:
                self.logger.info(f"Saga {saga_id} already waiting for confirmation; skipping run")
                # Pre-populate reservation info in adapter store
                try:
                    for s in steps:
                        if s.get("name") == "reserve_slot" and s.get("meta") and s["meta"].get("reservation_id"):
                            res_meta = s["meta"]
                            reservation_id = res_meta.get("reservation_id")
                            adapter = self.adapters.get("booking")
                            if adapter and hasattr(adapter, "reservations"):
                                adapter.reservations[reservation_id] = {
                                    "status": res_meta.get("status", "pending"),
                                    "payload": payload,
                                    "created_at": None,
                                }
                except Exception:
                    logging.debug("Suppressed exception", exc_info=True)
                return
            if current_state in (SagaState.SUCCEEDED.value, SagaState.COMPENSATED.value, SagaState.FAILED.value):
                self.logger.info(f"Saga {saga_id} in terminal state ({current_state}); skipping run")
                return
            
            # Resolve saga version
            resolved_version = self._resolve_saga_version(
                saga_type,
                saga.get("saga_version") or saga_version,
            )

            # Update to in_progress
            await self._update_saga_state(saga_id, SagaState.IN_PROGRESS.value, steps=steps)

            # Route based on saga_type + saga_version
            handler = self._get_saga_handler(saga_type, resolved_version, resume=False)
            if not handler:
                if saga_type not in SAGA_VERSION_REGISTRY:
                    raise ValueError(f"Unknown saga_type: {saga_type}")
                raise ValueError(f"Unsupported saga version: {saga_type}@{resolved_version}")

            await handler(
                saga_id,
                payload,
                steps,
                correlation_id,
                trace_context.get("trace_id"),
            )
        
        except Exception as e:
            self.logger.exception(f"❌ Saga execution failed: {saga_id}")
            # Update saga to failed
            steps = saga.get("steps", []) if 'saga' in locals() else []
            step = SagaStepRecord(
                name="saga_init",
                status=StepStatus.FAILED.value,
                error=str(e),
            )
            steps.append(step.to_dict())
            
            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={"error": str(e)},
            )

    async def resume_saga_on_confirm(
        self,
        saga_id: str,
        confirm_payload: Dict[str, Any],
        retry_count: int = 0,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Resume saga after user confirmation (with idempotency + distributed lock).
        
        Called by ActionRouter when user confirms action.
        
        Args:
            saga_id: ID of saga to resume
            confirm_payload: Confirmation data (e.g., {"confirmed": true, ...})
            retry_count: Current retry attempt
            max_retries: Maximum lock acquisition retries
            
        Returns:
            Result dict with status and outcome
        """
        confirm_payload_dict = confirm_payload
        if hasattr(confirm_payload, "model_dump"):
            confirm_payload_dict = confirm_payload.model_dump()
        elif hasattr(confirm_payload, "dict"):
            confirm_payload_dict = confirm_payload.dict()

        # Idempotency check
        cached = await self._check_idempotency(saga_id, "resume")
        if cached:
            self.logger.info(f"🔄 Idempotent saga resume detected: {saga_id}")
            return cached
        
        # Acquire distributed lock
        lock_acquired = await self.lock_manager.acquire(saga_id, "state")
        if not lock_acquired:
            if retry_count >= max_retries:
                self.logger.error(f"❌ Failed to acquire lock after {max_retries} retries: {saga_id}")
                result = {"status": "error", "error": "Failed to acquire lock"}
                await self._record_idempotency(saga_id, "resume", result)
                return result
            
            self.logger.warning(f"⏳ Failed to acquire lock for saga resume: {saga_id} (retry {retry_count + 1}/{max_retries})")
            await asyncio.sleep(0.5)
            return await self.resume_saga_on_confirm(saga_id, confirm_payload, retry_count + 1, max_retries)
        
        try:
            # Check timeout
            if await self._check_saga_timeout(saga_id):
                result = {"status": "error", "error": "Saga timed out"}
                await self._record_idempotency(saga_id, "resume", result)
                return result
            
            # Fetch saga
            saga = await self._get_saga(saga_id)
            if not saga:
                result = {"status": "error", "error": "Saga not found"}
                await self._record_idempotency(saga_id, "resume", result)
                return result
            
            if saga["state"] != SagaState.WAITING_CONFIRM.value:
                result = {
                    "status": "error",
                    "error": f"Saga not waiting for confirmation (state: {saga['state']})",
                }
                await self._record_idempotency(saga_id, "resume", result)
                return result
            
            steps = saga.get("steps", [])

            trace_context = (
                self._active_traces.get(saga_id)
                or self._resolve_trace_context_from_steps(steps)
                or self._ensure_trace_context(
                    saga_id=saga_id,
                    saga_type=saga.get("saga_type"),
                    action_id=saga.get("action_id"),
                    user_id=saga.get("user_id"),
                    correlation_id=saga.get("correlation_id"),
                    trace_id=None,
                )
            )
            
            # Mark confirmation as completed
            step = SagaStepRecord(
                name="user_confirm",
                status=StepStatus.SUCCEEDED.value,
                meta=confirm_payload_dict,
            )
            steps.append(step.to_dict())

            saga_type = saga.get("saga_type") or self._infer_saga_type_from_steps(steps)
            saga_version = self._resolve_saga_version(saga_type, saga.get("saga_version"))

            handler = self._get_saga_handler(saga_type, saga_version, resume=True)
            if not handler:
                if saga_type not in SAGA_VERSION_REGISTRY:
                    result = {
                        "status": "error",
                        "error": f"Unknown saga_type: {saga_type}",
                    }
                    await self._record_idempotency(saga_id, "resume", result)
                    return result
                result = {
                    "status": "error",
                    "error": f"Saga type '{saga_type}' with version '{saga_version}' does not support confirmation",
                }
                await self._record_idempotency(saga_id, "resume", result)
                return result

            result = await handler(
                saga_id=saga_id,
                saga=saga,
                steps=steps,
                confirm_payload=confirm_payload_dict,
                trace_context=trace_context,
            )
            await self._record_idempotency(saga_id, "resume", result)
            return result
        
        except Exception as e:
            self.logger.exception(f"❌ Resume failed: {saga_id}")
            result = {"status": "error", "error": str(e)}
            await self._record_idempotency(saga_id, "resume", result)
            return result
        finally:
            await self.lock_manager.release(saga_id, "state")

    async def get_saga_state(self, saga_id: str) -> Optional[Dict[str, Any]]:
        """Public accessor for saga state (for saga.status requests)."""
        try:
            return await self._get_saga(saga_id)
        except Exception as e:
            self.logger.warning(f"Failed to fetch saga state: {saga_id}: {e}")
            return None

    async def get_saga_audit(self, saga_id: str) -> Dict[str, Any]:
        """Fetch saga audit info (steps + compensation history)."""
        saga = await self._get_saga(saga_id)
        if not saga:
            return {"error": "Saga not found", "saga_id": saga_id}

        compensations = []
        try:
            query = """
            SELECT compensation_id, original_operation, compensation_operation,
                   compensation_result, reason, created_at
            FROM compensation_history
            WHERE saga_id = $1
            ORDER BY created_at ASC
            """
            rows = await self.db.fetch(query, saga_id)
            compensations = [dict(r) for r in rows]
        except Exception as e:
            self.logger.warning(f"Failed to fetch compensation history for {saga_id}: {e}")

        return {
            "saga_id": saga_id,
            "saga_type": saga.get("saga_type"),
            "state": saga.get("state"),
            "steps": saga.get("steps") or [],
            "result": saga.get("result"),
            "updated_at": saga.get("updated_at"),
            "compensation_history": compensations,
        }
    
    async def _compensate_saga(
        self,
        saga_id: str,
        saga: Dict[str, Any],
        steps: List[Dict[str, Any]],
        trigger_error: Exception,
    ):
        """
        Trigger compensation (rollback) on saga failure.
        
        Calls adapter.compensate() for each completed step in LIFO order (reverse).
        Compensation is idempotent (tracked by step.compensated flag).
        """
        try:
            self.logger.warning(f"⚠️  Compensating saga {saga_id}: {trigger_error}")
            
            compensated_ops = await self._get_compensated_operations(saga_id)
            
            trace_context = (
                self._active_traces.get(saga_id)
                or self._resolve_trace_context_from_steps(steps)
                or self._ensure_trace_context(
                    saga_id=saga_id,
                    saga_type=saga.get("saga_type"),
                    action_id=saga.get("action_id"),
                    user_id=saga.get("user_id"),
                    correlation_id=saga.get("correlation_id"),
                    trace_id=None,
                )
            )

            # Acquire lock for compensation
            lock_acquired = await self.lock_manager.acquire(saga_id, "state")
            if not lock_acquired:
                self.logger.warning(f"⏳ Failed to acquire lock for compensation: {saga_id}")
                return
            
            try:
                await self._update_saga_state(saga_id, SagaState.COMPENSATING.value, steps=steps)
                
                # Identify steps to compensate (in LIFO order)
                compensable_steps = [
                    s for s in reversed(steps)
                    if s.get("status") == StepStatus.SUCCEEDED.value
                    and not s.get("compensated", False)
                    and (s.get("compensatable") or s.get("name") in COMPENSATION_STEP_MAP)
                ]
                
                compensation_results = []
                
                for step_record in compensable_steps:
                    step_name = step_record.get("name")
                    adapter_type = step_record.get("adapter_type") or COMPENSATION_STEP_MAP.get(step_name)
                    
                    if not adapter_type:
                        continue

                    original_op = f"{adapter_type}.{step_name}"
                    if original_op in compensated_ops:
                        compensation_results.append({
                            "step": step_name,
                            "status": "skipped",
                            "reason": "already_compensated",
                        })
                        continue

                    cached = await self._check_idempotency(saga_id, f"compensate:{step_name}")
                    if cached:
                        compensation_results.append({
                            "step": step_name,
                            "status": "skipped",
                            "reason": "idempotent_cache",
                        })
                        continue
                    
                    adapter = self.adapters.get(adapter_type)
                    if not adapter or not hasattr(adapter, 'compensate'):
                        self.logger.warning(f"No compensate method for {adapter_type}")
                        continue

                    if hasattr(adapter, "validate_compensation"):
                        try:
                            verdict = await self._call_adapter_method(
                                adapter,
                                "validate_compensation",
                                saga["payload"],
                                trace_context=trace_context,
                            )
                        except Exception as verdict_error:
                            verdict = {
                                "allow": False,
                                "reason": f"validation_failed: {verdict_error}",
                            }

                        if isinstance(verdict, dict) and not verdict.get("allow", True):
                            self.logger.warning(
                                f"Compensation blocked for {adapter_type}: {verdict.get('reason')}"
                            )
                            comp_step = SagaStepRecord(
                                name=f"compensate_{adapter_type}",
                                status=StepStatus.FAILED.value,
                                error=f"compensation_blocked: {verdict.get('reason')}",
                                meta={"verdict": verdict},
                            )
                            steps.append(comp_step.to_dict())
                            compensation_results.append({
                                "step": step_name,
                                "status": "skipped",
                                "reason": verdict.get("reason"),
                            })
                            continue
                    
                    circuit_breaker = self._get_circuit_breaker(adapter_type)
                    
                    # Check circuit breaker
                    if not circuit_breaker.can_execute():
                        self.logger.error(f"🔴 Circuit breaker open, skipping compensation for {adapter_type}")
                        continue
                    
                    try:
                        span_id = self.telemetry_collector.start_adapter_call(
                            trace_context.get("root_span_id"),
                            adapter_type,
                            "compensate",
                            payload_size=self._safe_payload_size(saga.get("payload") or {}),
                            trace_id=trace_context.get("trace_id"),
                            saga_id=saga_id,
                            correlation_id=trace_context.get("correlation_id"),
                        )
                        # Execute compensation with retry
                        comp_payload = saga.get("payload")
                        if isinstance(comp_payload, dict):
                            comp_payload = {
                                **comp_payload,
                                "_compensation_context": {
                                    "saga_id": saga_id,
                                    "step_name": step_name,
                                    "step_meta": step_record.get("meta"),
                                },
                            }
                        else:
                            comp_payload = {
                                "payload": comp_payload,
                                "_compensation_context": {
                                    "saga_id": saga_id,
                                    "step_name": step_name,
                                    "step_meta": step_record.get("meta"),
                                },
                            }

                        comp_res = await retry_with_backoff(
                            func=lambda: self._call_adapter_method(
                                adapter,
                                "compensate",
                                comp_payload,
                                trace_context=trace_context,
                            ),
                            config=self.retry_config,
                            operation_name=f"{adapter_type}.compensate",
                            logger_instance=self.logger,
                        )
                        circuit_breaker.record_success()
                        self.telemetry_collector.end_span(span_id, status="OK")
                        
                        comp_step = SagaStepRecord(
                            name=f"compensate_{adapter_type}",
                            status=StepStatus.SUCCEEDED.value,
                            meta=comp_res,
                        )
                        steps.append(comp_step.to_dict())
                        
                        # Mark original step as compensated
                        step_record["compensated"] = True
                        
                        # Record compensation in audit
                        await self._record_compensation(
                            saga_id,
                            original_op,
                            f"{adapter_type}.compensate",
                            comp_res,
                            str(trigger_error),
                        )
                        await self._record_idempotency(
                            saga_id,
                            f"compensate:{step_name}",
                            comp_res,
                        )
                        
                        compensation_results.append({
                            "step": step_name,
                            "status": "succeeded",
                            "result": comp_res,
                        })
                        
                        self.logger.info(f"✅ Compensation succeeded for {step_name}: {saga_id}")
                    
                    except Exception as comp_error:
                        await circuit_breaker.record_failure()
                        if "span_id" in locals():
                            self.telemetry_collector.end_span(span_id, status="ERROR", error=str(comp_error))
                        self.logger.exception(f"❌ Compensation failed for {step_name}: {saga_id}")
                        
                        comp_step = SagaStepRecord(
                            name=f"compensate_{adapter_type}",
                            status=StepStatus.FAILED.value,
                            error=str(comp_error),
                        )
                        steps.append(comp_step.to_dict())
                        
                        compensation_results.append({
                            "step": step_name,
                            "status": "failed",
                            "error": str(comp_error),
                        })
                
                # Determine final state
                if not compensation_results:
                    final_state = SagaState.FAILED.value
                else:
                    all_compensated = all(r["status"] == "succeeded" for r in compensation_results)
                    final_state = SagaState.COMPENSATED.value if all_compensated else SagaState.FAILED.value
                
                await self._update_saga_state(
                    saga_id,
                    final_state,
                    steps=steps,
                    result={
                        "trigger_error": str(trigger_error),
                        "compensation_results": compensation_results,
                    },
                )
                
                self.logger.info(f"✅ Compensation complete: {saga_id} (state: {final_state})")
                
                # Record idempotency snapshot (best-effort)
                await self._record_idempotency(saga_id, "compensate:summary", compensation_results)
            
            finally:
                await self.lock_manager.release(saga_id, "state")
        
        except Exception as e:
            self.logger.exception(f"❌ Compensation orchestration failed: {saga_id}")
            
            # Mark as failed (couldn't even compensate)
            await self._update_saga_state(
                saga_id,
                SagaState.FAILED.value,
                steps=steps,
                result={
                    "error": str(trigger_error),
                    "compensation_error": str(e),
                },
            )
    
    # =========================================================================
    # Database Operations
    # =========================================================================
    
    async def _get_saga(self, saga_id: str) -> Optional[Dict[str, Any]]:
        """Fetch saga from database."""
        if self.db is None:
            if self._testing_mode:
                return None
            raise RuntimeError("Saga DB not initialized")
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM sagas WHERE saga_id = $1",
                saga_id,
            )
            return dict(row) if row else None
        except Exception as e:
            self.logger.error(f"Failed to fetch saga {saga_id}: {e}")
            return None
    
    async def _update_saga_state(
        self,
        saga_id: str,
        state: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        result: Optional[Dict[str, Any]] = None,
    ):
        """Update saga state and steps in database."""
        if self.db is None:
            if self._testing_mode:
                await self._emit_saga_update(saga_id, state, steps, result)
                return
            raise RuntimeError("Saga DB not initialized")
        try:
            trace_context = self._active_traces.get(saga_id)
            if steps is not None and trace_context:
                for step in steps:
                    if isinstance(step, dict):
                        step.setdefault("trace_id", trace_context.get("trace_id"))
                        step.setdefault("correlation_id", trace_context.get("correlation_id"))

            db_span_id = None
            if trace_context:
                db_span_id = self.telemetry_collector.start_span(
                    "db.update_saga",
                    attributes={
                        "saga_id": saga_id,
                        "state": state,
                        "trace_id": trace_context.get("trace_id"),
                        "correlation_id": trace_context.get("correlation_id"),
                    },
                    trace_id=trace_context.get("trace_id"),
                    parent_span_id=trace_context.get("root_span_id"),
                )

            query_with_steps = """
            UPDATE sagas
            SET state = $1, steps = $2, result = $3, updated_at = NOW()
            WHERE saga_id = $4
            """

            query_without_steps = """
            UPDATE sagas
            SET state = $1, result = $2, updated_at = NOW()
            WHERE saga_id = $3
            """
            
            if steps is None:
                await self.db.execute(
                    query_without_steps,
                    state,
                    json.dumps(result) if result is not None else None,
                    saga_id,
                )
            else:
                await self.db.execute(
                    query_with_steps,
                    state,
                    json.dumps(steps),
                    json.dumps(result) if result is not None else None,
                    saga_id,
                )

            await self._emit_saga_update(saga_id, state, steps, result)

            if db_span_id:
                self.telemetry_collector.end_span(db_span_id, status="OK")

            if state in (
                SagaState.SUCCEEDED.value,
                SagaState.COMPENSATED.value,
                SagaState.FAILED.value,
                SagaState.ARCHIVED.value,
            ):
                if saga_id in self._active_sagas:
                    if state in (SagaState.FAILED.value, SagaState.COMPENSATED.value):
                        self.prom_metrics.record_saga_failed()
                    start_time = self._saga_start_times.pop(saga_id, None)
                    if start_time is not None:
                        self.prom_metrics.observe_saga_duration(time.perf_counter() - start_time)
                    self._active_sagas.discard(saga_id)
                    self.prom_metrics.set_active_sagas_count(len(self._active_sagas))

            if trace_context and state in (
                SagaState.SUCCEEDED.value,
                SagaState.COMPENSATED.value,
                SagaState.FAILED.value,
                SagaState.ARCHIVED.value,
            ):
                root_span_id = trace_context.get("root_span_id")
                if root_span_id:
                    status = "OK" if state in (SagaState.SUCCEEDED.value, SagaState.COMPENSATED.value) else "ERROR"
                    error_message = None
                    if status == "ERROR" and result:
                        error_message = json.dumps(result)
                    self.telemetry_collector.end_span(root_span_id, status=status, error=error_message)
                self._active_traces.pop(saga_id, None)
        
        except Exception as e:
            if "db_span_id" in locals() and db_span_id:
                self.telemetry_collector.end_span(db_span_id, status="ERROR", error=str(e))
            self.logger.error(f"Failed to update saga state {saga_id}: {e}")
            raise

    async def _emit_saga_update(
        self,
        saga_id: str,
        state: str,
        steps: Optional[List[Dict[str, Any]]],
        result: Optional[Dict[str, Any]],
    ):
        """Emit saga update to external consumers (e.g., WebSocket gateway)."""
        if not self.saga_update_handler:
            return

        try:
            saga = await self._get_saga(saga_id)
            trace_context = self._active_traces.get(saga_id) or self._resolve_trace_context_from_steps(steps)
            payload = {
                "type": "saga.update",
                "session_id": saga.get("user_id") if saga else None,
                "saga_id": saga_id,
                "saga_type": saga.get("saga_type") if saga else None,
                "saga_version": saga.get("saga_version") if saga else None,
                "state": state,
                "steps": steps or [],
                "result": result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "correlation_id": trace_context.get("correlation_id") if trace_context else saga.get("correlation_id"),
                "trace_id": trace_context.get("trace_id") if trace_context else None,
            }

            handler = self.saga_update_handler
            if asyncio.iscoroutinefunction(handler):
                await handler(payload)
            else:
                maybe = handler(payload)
                if asyncio.iscoroutine(maybe):
                    await maybe
        except Exception as e:
            self.logger.warning(f"Failed to emit saga update: {e}")
    
    async def _record_compensation(
        self,
        saga_id: str,
        original_op: str,
        compensation_op: str,
        comp_result: Any,
        reason: str,
    ):
        """Record compensation in audit table."""
        if self.db is None:
            if self._testing_mode:
                return
            raise RuntimeError("Saga DB not initialized")
        try:
            query = """
            INSERT INTO compensation_history
            (compensation_id, saga_id, original_operation, compensation_operation, compensation_result, reason)
            VALUES ($1, $2, $3, $4, $5, $6)
            """
            
            comp_id = str(uuid.uuid4())
            
            await self.db.execute(
                query,
                comp_id,
                saga_id,
                original_op,
                compensation_op,
                json.dumps(comp_result),
                reason,
            )
        
        except Exception as e:
            self.logger.warning(f"Failed to record compensation: {e}")

    async def _get_compensated_operations(self, saga_id: str) -> set:
        """Return set of original_operations already compensated for this saga."""
        if self.db is None:
            if self._testing_mode:
                return set()
            raise RuntimeError("Saga DB not initialized")
        try:
            query = """
            SELECT original_operation
            FROM compensation_history
            WHERE saga_id = $1
            """

            rows = await self.db.fetch(query, saga_id)
            return {row["original_operation"] for row in rows}
        except Exception as e:
            self.logger.error(f"CRITICAL: DB unavailable during compensation check: {e}")
            raise

    async def _check_compensation_exists(self, saga_id: str) -> bool:
        """
        Check if compensation already exists in DB (idempotency across restarts).
        
        Args:
            saga_id: Saga ID to check
            
        Returns:
            True if compensation already executed, False otherwise
        """
        if self.db is None:
            if self._testing_mode:
                return False
            raise RuntimeError("Saga DB not initialized")
        try:
            query = """
            SELECT COUNT(*) as count
            FROM compensation_history
            WHERE saga_id = $1
            """
            
            row = await self.db.fetchrow(query, saga_id)
            return row["count"] > 0 if row else False
        
        except Exception as e:
            self.logger.error(f"Failed to check compensation history: {e}")
            # Fail-closed to avoid double-compensation on DB errors
            raise



