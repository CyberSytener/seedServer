"""Optional router registration — extracted from app.main.

All try/except guarded router imports live here so main.py stays lean.

Policy: only ``ImportError`` (including ``ModuleNotFoundError``) is suppressed.
Any other exception during import or ``include_router`` propagates to the
caller so startup failures are visible, not silently swallowed.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import FastAPI

from app.infrastructure.db.sqlite import DB


def register_optional_routers(
    app: FastAPI,
    *,
    settings: Any,
    db: DB,
    get_neoeats_db: Callable[..., Awaitable[Any]],
) -> None:
    """Register all optional (try/except-guarded) routers onto *app*."""

    from app.settings import get_settings

    # Include prompt testing API if available and enabled
    if get_settings().prompt_test_mode:
        try:
            from app.api.prompt_testing import router as prompt_testing_router
            app.include_router(prompt_testing_router)
            logging.info("Prompt testing API endpoints added")
        except ImportError as e:
            logging.warning(f"Prompt testing API not available: {e}")

    # Include streaming and async job queue APIs for better scalability
    try:
        from app.api.lesson_stream import router as lesson_stream_router
        app.include_router(lesson_stream_router)
        logging.info("Streaming lesson generation API enabled")
    except ImportError as e:
        logging.warning(f"Lesson streaming API not available: {e}")

    try:
        from app.api.job_queue import router as job_queue_router
        app.include_router(job_queue_router)
        logging.info("Job queue API enabled for background processing")
    except ImportError as e:
        logging.warning(f"Job queue API not available: {e}")

    try:
        from app.api.diagnostic_stream import router as diagnostic_stream_router
        app.include_router(diagnostic_stream_router)
        logging.info("Streaming diagnostic generation API enabled")
    except ImportError as e:
        logging.warning(f"Diagnostic streaming API not available: {e}")

    # Include Pipeline API (SSE streaming endpoints)
    try:
        from app.api.pipeline import router as pipeline_router
        app.include_router(pipeline_router)
        logging.info("Pipeline API enabled (SSE streaming)")
    except ImportError as e:
        logging.warning(f"Pipeline API not available: {e}")

    # Include Module Registry API
    try:
        from app.api.modes import router as modes_router
        app.include_router(modes_router)
        logging.info("Module registry API enabled (/v1/modes)")
    except ImportError as e:
        logging.warning(f"Module registry API not available: {e}")

    # Include Console Runtime API (modules/flows/runs facade)
    try:
        from app.api.console import create_console_runtime_router

        app.include_router(create_console_runtime_router())
        logging.info("Console runtime API enabled (/v1/modules,/v1/flows,/v1/runs)")
    except ImportError as e:
        logging.warning(f"Console runtime API not available: {e}")

    # Include Marketplace API
    try:
        from app.api.marketplace_routes import build_marketplace_router

        app.include_router(build_marketplace_router(db=db))
        logging.info("Marketplace API enabled (/v1/marketplace)")
    except ImportError as e:
        logging.warning(f"Marketplace API not available: {e}")

    # Include Dynamic Test API
    if settings.public_mode:
        logging.info("Dynamic Test API disabled in PUBLIC_MODE")
    else:
        try:
            from app.api.dynamic_test import router as dynamic_test_router
            app.include_router(dynamic_test_router)
            logging.info("Dynamic Test API enabled (custom test generation)")
        except ImportError as e:
            logging.warning(f"Dynamic Test API not available: {e}")

    # Include Learning Path API (Blueprint Pattern)
    try:
        from app.api.path import router as path_router
        app.include_router(path_router)
        logging.info("Learning Path API enabled (Blueprint Pattern)")
    except ImportError as e:
        logging.warning(f"Learning Path API not available: {e}")

    # Include Performance Metrics API
    try:
        from app.api.metrics import router as metrics_router
        app.include_router(metrics_router)
        logging.info("Performance metrics API enabled")
    except ImportError as e:
        logging.warning(f"Metrics API not available: {e}")

    # Include basic HTTP actions API
    try:
        from app.api.http import router as http_actions_router
        app.include_router(http_actions_router)
        logging.info("Actions API enabled")
    except ImportError as e:
        logging.warning(f"Actions API not available: {e}")

    # Include Photo Editing API
    try:
        from app.api.photo import router as photo_router
        app.include_router(photo_router)
        logging.info("Photo editing API enabled (portrait enhancement)")
    except ImportError as e:
        logging.warning(f"Photo editing API not available: {e}")

    # Include Receipt Scanning API
    try:
        from app.api.receipts import build_receipts_router

        app.include_router(build_receipts_router(get_neoeats_db))
        logging.info("Receipt scanning API enabled")
    except ImportError as e:
        logging.warning(f"Receipt scanning API not available: {e}")

    # Include Saga Health Check API
    try:
        from app.core.realtime.sagas.saga_health import saga_health_router
        app.include_router(saga_health_router)
        logging.info("Saga health check API enabled")
    except ImportError as e:
        logging.warning(f"Saga health check API not available: {e}")

    # Include Saga Blueprints API
    try:
        from app.api.saga_blueprints import router as saga_blueprints_router
        app.include_router(saga_blueprints_router)
        logging.info("Saga blueprints API enabled")
    except ImportError as e:
        logging.warning(f"Saga blueprints API not available: {e}")

    # Include Agent Integration API
    try:
        from app.api.agent_integration import router as agent_integration_router

        app.include_router(agent_integration_router)
        logging.info("Agent integration API enabled (/v1/catalog,/v1/blueprints)")
    except ImportError as e:
        logging.warning(f"Agent integration API not available: {e}")

    # Include Registry Schema API
    try:
        from app.api.registry_schema import router as registry_schema_router
        app.include_router(registry_schema_router)
        logging.info("Registry schema API enabled")
    except ImportError as e:
        logging.warning(f"Registry schema API not available: {e}")

    # Include Cooking Plan Generation API
    try:
        from app.api.cooking import router as cooking_router
        app.include_router(cooking_router)
        logging.info("Cooking plan API enabled")
    except ImportError as e:
        logging.warning(f"Cooking plan API not available: {e}")

    # Include deprecated job stubs (return 501)
    try:
        from app.api.deprecated_routes import router as deprecated_router
        app.include_router(deprecated_router)
    except ImportError as e:
        logging.warning(f"Deprecated routes not available: {e}")

    # Include Agent Session API (Phase 7)
    try:
        from app.api.agent_routes import build_agent_router
        from app.core.agent.session_store import AgentSessionStore
        from app.core.agent.tool_registry import ToolRegistry
        from app.infrastructure.db.async_sqlite import get_async_db
        from app.core.blocks import BlockRegistry

        async_db = get_async_db()
        agent_session_store = AgentSessionStore(async_db)

        block_registry = BlockRegistry.get_default() if hasattr(BlockRegistry, "get_default") else BlockRegistry()
        agent_tool_registry = ToolRegistry(block_registry)

        agent_router = build_agent_router(
            session_store=agent_session_store,
            tool_registry=agent_tool_registry,
            action_router=getattr(app.state, "action_router", None),
            llm_service=getattr(app.state, "llm_service", None),
        )
        app.include_router(agent_router)
        logging.info("Agent sessions API enabled (/v1/agent/sessions, /v1/agent/tools)")
    except ImportError as e:
        logging.warning(f"Agent sessions API not available: {e}")
