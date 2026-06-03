"""Application lifespan: startup tasks and graceful shutdown."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from app.core.realtime.ws_consumers import (
    forward_router_responses,
    consume_action_router_messages,
)
from app.infrastructure.dev_helpers import (
    seed_store_inventory_catalog as _seed_store_inventory_catalog,
)
from app.infrastructure.db.seed_catalog import (
    log_catalog_seed_failure as _log_catalog_seed_failure,
)
from app.infrastructure.monitoring.monitoring.metrics import shutdown_metrics


@asynccontextmanager
async def app_lifespan(app):
    """Startup / shutdown lifecycle for the FastAPI application."""
    # ---- Startup ----
    app.state.realtime_tasks = []
    app.state.saga_db = None

    saga_db_url = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL")
    if saga_db_url:
        try:
            from app.infrastructure.db.postgres import AsyncPGDatabase

            app.state.saga_db = await AsyncPGDatabase.get_shared(
                saga_db_url,
                min_size=int(os.getenv("SAGA_DB_POOL_MIN", "5")),
                max_size=int(os.getenv("SAGA_DB_POOL_MAX", "20")),
            )
        except Exception as e:
            logging.warning("Saga DB pool init failed: %s", e)
    else:
        logging.info("Saga DB pool disabled: Postgres not configured (SEED_SAGA_DB_URL/DATABASE_URL).")

    if getattr(app.state, "gateway", None) and getattr(app.state, "response_queue", None):
        task = asyncio.create_task(
            forward_router_responses(app.state.gateway, app.state.response_queue)
        )
        app.state.realtime_tasks.append(task)

    if getattr(app.state, "action_router", None) and getattr(app.state, "action_router_queue", None) and getattr(app.state, "response_queue", None):
        task = asyncio.create_task(
            consume_action_router_messages(
                app.state.action_router,
                app.state.action_router_queue,
                app.state.response_queue,
                app.state.seed.redis,
            )
        )
        app.state.realtime_tasks.append(task)

    if getattr(app.state, "saga_orchestrator", None) and app.state.saga_orchestrator.async_mode:
        try:
            await app.state.saga_orchestrator.init_async()
        except Exception as e:
            logging.warning(f"SagaOrchestrator async init failed: {e}")

    if getattr(app.state, "saga_waiting_confirm_archiver_factory", None):
        try:
            task = asyncio.create_task(app.state.saga_waiting_confirm_archiver_factory())
            app.state.realtime_tasks.append(task)
        except Exception as e:
            logging.warning(f"Waiting-confirm archiver start failed: {e}")

    if getattr(app.state, "saga_recovery_worker_factory", None):
        try:
            task = asyncio.create_task(app.state.saga_recovery_worker_factory())
            app.state.realtime_tasks.append(task)
        except Exception as e:
            logging.warning(f"Saga recovery worker start failed: {e}")

    if getattr(app.state, "saga_dlq_maintenance_factory", None):
        try:
            task = asyncio.create_task(app.state.saga_dlq_maintenance_factory())
            app.state.realtime_tasks.append(task)
        except Exception as e:
            logging.warning(f"Saga DLQ maintenance worker start failed: {e}")

    if getattr(app.state, "saga_event_bus_consumer_factory", None):
        try:
            app.state.saga_event_bus_task = asyncio.create_task(
                app.state.saga_event_bus_consumer_factory()
            )
            app.state.realtime_tasks.append(app.state.saga_event_bus_task)
        except Exception as e:
            logging.warning(f"SagaEventBus consumer start failed: {e}")

    try:
        await _seed_store_inventory_catalog(app)
    except Exception as e:
        _log_catalog_seed_failure(e)

    yield

    # ---- Shutdown ----
    for task in getattr(app.state, "realtime_tasks", []):
        task.cancel()
    for task in getattr(app.state, "realtime_tasks", []):
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
    if getattr(app.state, "saga_orchestrator", None) and app.state.saga_orchestrator.async_mode:
        try:
            await app.state.saga_orchestrator.close_async()
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
    try:
        redis_client = app.state.seed.redis
        if hasattr(redis_client, "aclose"):
            await redis_client.aclose()
        else:
            await redis_client.close()
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
    try:
        app.state.seed.db.close()
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
    try:
        from app.infrastructure.db.postgres import AsyncPGDatabase

        await AsyncPGDatabase.close_shared()
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
    try:
        shutdown_metrics()
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
