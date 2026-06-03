"""Realtime infrastructure wiring: saga orchestrator, action router, gateway, and related components."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Tuple

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.core.realtime.action_router import ActionRouter
from app.core.realtime.feature_flags import get_flag_manager
from app.core.realtime.sagas.orchestrator import SagaOrchestrator
from app.api.ws.gateway import WebSocketGateway
from app.infrastructure.db.sqlite import DB
from app.services.order_stream import OrderStreamHub
from app.settings import Settings


def wire_realtime_infrastructure(
    app: FastAPI,
    *,
    settings: Settings,
    db: DB,
    r: aioredis.Redis,
    response_queue: asyncio.Queue,
    action_router_queue: asyncio.Queue,
) -> Tuple[SagaOrchestrator | None, ActionRouter, OrderStreamHub]:
    """Set up saga orchestrator, action router, gateway, and all realtime infrastructure.

    Returns ``(saga_orchestrator, action_router, order_stream)``.
    """

    # ------------------------------------------------------------------
    # Saga orchestrator
    # ------------------------------------------------------------------
    async def saga_update_handler(payload: Dict[str, Any]) -> None:
        await response_queue.put(payload)

    saga_db_url = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL")
    saga_redis_url = settings.redis_url
    saga_orchestrator: SagaOrchestrator | None = None

    if saga_db_url:
        try:
            from app.infrastructure.db.postgres import AsyncPGDatabase

            async def _create_saga_db():
                return await AsyncPGDatabase.get_shared(
                    saga_db_url,
                    min_size=int(os.getenv("SAGA_DB_POOL_MIN", "5")),
                    max_size=int(os.getenv("SAGA_DB_POOL_MAX", "20")),
                )

            saga_orchestrator = SagaOrchestrator(
                db_connection_string=saga_db_url,
                adapter_registry={},
                async_mode=True,
                saga_update_handler=saga_update_handler,
                redis_url=saga_redis_url,
                db_factory=_create_saga_db,
            )
        except Exception as e:
            logging.warning(f"SagaOrchestrator disabled: {e}")
    else:
        logging.info("SagaOrchestrator disabled: Postgres not configured (SEED_SAGA_DB_URL/DATABASE_URL).")

    # ------------------------------------------------------------------
    # Saga adapters
    # ------------------------------------------------------------------
    if saga_orchestrator is not None:
        try:
            from app.core.realtime.sagas.saga_integration import (
                create_cv_adapter,
                create_learning_plan_adapter,
                create_diagnostic_adapter,
                create_portfolio_adapter,
                create_skill_matrix_adapter,
                create_career_education_adapter,
                create_job_discovery_adapter,
                create_outreach_email_adapter,
            )
            from app.core.realtime.optimized.cv_processor import CVProcessor
            from app.infrastructure.realtime.integrations.outlook_email_client import (
                OutlookEmailClient,
                InMemoryTokenStore,
            )

            cv_processor = CVProcessor()

            from app.core.realtime.sagas.llm_adapter import SagaLLMPipelineAdapter

            saga_orchestrator.adapters["llm_pipeline"] = SagaLLMPipelineAdapter(settings)
            saga_orchestrator.adapters["llm"] = saga_orchestrator.adapters["llm_pipeline"]

            saga_orchestrator.adapters["learning_plan"] = create_learning_plan_adapter(db)
            saga_orchestrator.adapters["diagnostic"] = create_diagnostic_adapter(db)
            saga_orchestrator.adapters["portfolio"] = create_portfolio_adapter()
            saga_orchestrator.adapters["skill_matrix"] = create_skill_matrix_adapter(db)
            saga_orchestrator.adapters["cv"] = create_cv_adapter(cv_processor)
            saga_orchestrator.adapters["career_education"] = create_career_education_adapter(db)
            saga_orchestrator.adapters["job_search"] = create_job_discovery_adapter(
                country_code=os.getenv("JOB_SEARCH_COUNTRY_CODE", "com")
            )

            outlook_client_id = os.getenv("OUTLOOK_CLIENT_ID")
            outlook_client_secret = os.getenv("OUTLOOK_CLIENT_SECRET")
            outlook_tenant_id = os.getenv("OUTLOOK_TENANT_ID")
            default_sender = os.getenv("OUTLOOK_DEFAULT_SENDER") or os.getenv("OUTREACH_DEFAULT_SENDER")
            email_client = None
            if outlook_client_id and outlook_client_secret and outlook_tenant_id:
                email_client = OutlookEmailClient(
                    client_id=outlook_client_id,
                    client_secret=outlook_client_secret,
                    tenant_id=outlook_tenant_id,
                    token_store=InMemoryTokenStore(),
                )
            saga_orchestrator.adapters["email_outreach"] = create_outreach_email_adapter(
                email_client,
                default_sender,
            )
        except Exception as e:
            logging.warning(f"Failed to register saga adapters: {e}")

        # Background worker factories
        from app.core.realtime.sagas.background_workers import (
            archive_waiting_confirm_loop,
            recover_stuck_sagas_loop,
            dlq_maintenance_loop,
        )

        app.state.saga_waiting_confirm_archiver_factory = lambda: archive_waiting_confirm_loop(saga_orchestrator)
        app.state.saga_recovery_worker_factory = lambda: recover_stuck_sagas_loop(saga_orchestrator)
        app.state.saga_dlq_maintenance_factory = lambda: dlq_maintenance_loop(saga_orchestrator)

    # ------------------------------------------------------------------
    # Feature flags & idempotency
    # ------------------------------------------------------------------
    feature_flags = get_flag_manager()

    try:
        import redis as redis_sync
        from app.core.realtime.redis_idempotency import RedisIdempotencyManager

        sync_redis = redis_sync.Redis.from_url(settings.redis_url, decode_responses=False)
        idempotency_manager = RedisIdempotencyManager(sync_redis, ttl_seconds=3600)
    except Exception as e:
        logging.warning(f"Redis idempotency unavailable, falling back to in-memory: {e}")
        idempotency_manager = None

    # ------------------------------------------------------------------
    # Saga event bus
    # ------------------------------------------------------------------
    saga_event_bus = None
    saga_event_bus_task = None
    saga_event_bus_consumer_factory = None

    if saga_orchestrator is not None:
        try:
            from app.core.realtime.sagas.saga_event_bus import SagaEventBus

            saga_event_bus = SagaEventBus(redis_url=settings.redis_url)

            async def _handle_saga_start(event: Dict[str, Any]) -> None:
                await saga_orchestrator.start_saga(
                    action_id=event.get("action_id"),
                    saga_type=event.get("saga_type"),
                    payload=event.get("payload") or {},
                    user_id=event.get("user_id"),
                    correlation_id=event.get("correlation_id"),
                    trace_id=event.get("trace_id"),
                )

            async def _consume_saga_events():
                await saga_event_bus.start_consumer(_handle_saga_start)

            saga_event_bus_consumer_factory = _consume_saga_events
        except Exception as e:
            logging.warning(f"SagaEventBus disabled: {e}")

    # ------------------------------------------------------------------
    # Pending action store
    # ------------------------------------------------------------------
    pending_action_store = None
    try:
        from app.core.realtime.pending_store import RedisPendingActionStore

        pending_action_store = RedisPendingActionStore(
            r,
            namespace=f"{settings.redis_namespace}:pending_actions",
        )
    except Exception as e:
        logging.warning(f"Pending action store disabled: {e}")

    # ------------------------------------------------------------------
    # Action router
    # ------------------------------------------------------------------
    async def _notify_action_deferred(payload: Dict[str, Any]) -> None:
        await response_queue.put(payload)

    confirmation_timeout_seconds = int(os.getenv("ACTION_CONFIRM_TIMEOUT_SECONDS", "60"))

    action_router = ActionRouter(
        saga_orchestrator=saga_orchestrator,
        feature_flag_manager=feature_flags,
        idempotency_manager=idempotency_manager,
        saga_event_bus=saga_event_bus,
        confirmation_timeout_seconds=confirmation_timeout_seconds,
        pending_action_store=pending_action_store,
        confirmation_notifier=_notify_action_deferred,
    )

    # ------------------------------------------------------------------
    # WebSocket gateway
    # ------------------------------------------------------------------
    gateway = None
    try:
        ws_send_timeout = float(os.getenv("WS_SEND_TIMEOUT_SECONDS", "5"))
        gateway = WebSocketGateway(
            app=app,
            redis_client=r,
            action_router_queue=action_router_queue,
            send_timeout_seconds=ws_send_timeout,
        )
    except Exception as e:
        logging.warning(f"WebSocketGateway disabled: {e}")

    # ------------------------------------------------------------------
    # Attach to app state
    # ------------------------------------------------------------------
    app.state.gateway = gateway
    app.state.action_router = action_router
    app.state.response_queue = response_queue
    app.state.action_router_queue = action_router_queue
    app.state.saga_orchestrator = saga_orchestrator
    app.state.saga_event_bus = saga_event_bus
    app.state.saga_event_bus_task = saga_event_bus_task
    app.state.saga_event_bus_consumer_factory = saga_event_bus_consumer_factory

    # ------------------------------------------------------------------
    # Order stream
    # ------------------------------------------------------------------
    order_stream = OrderStreamHub()
    app.state.order_stream = order_stream
    if saga_orchestrator is not None:
        saga_orchestrator.order_stream = order_stream

    return saga_orchestrator, action_router, order_stream
