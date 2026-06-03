from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from dataclasses import dataclass
import dataclasses
from pathlib import Path
from typing import Any, Dict

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from prometheus_client import make_asgi_app
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="pythonjsonlogger.jsonlogger has been moved")
    from pythonjsonlogger import jsonlogger

from app.core.auth import authenticate
from app.infrastructure.db.sqlite import DB, seed_defaults
from app.infrastructure.monitoring.monitoring.metrics import init_metrics, shutdown_metrics

from app.api.auth_routes import build_auth_router
from app.api.admin_routes import build_admin_router
from app.api.jobs_routes import build_jobs_router
from app.api.lessons_routes import build_lessons_router
from app.api.diagnostics_routes import build_diagnostics_router
from app.api.career_routes import build_career_router
from app.api.actions_endpoint import build_actions_endpoint_router
from app.api.actions_saga_routes import build_actions_saga_router
from app.core.realtime.ws_consumers import (
    _build_action_from_message,
)
from app.api.inventory_orders_vision_routes import build_inventory_orders_vision_router
from app.api.neoeats_profile_routes import build_neoeats_profile_router
from app.api.learning_feedback_monitoring_routes import build_learning_feedback_monitoring_router
from app.api.tenant_governance_routes import build_tenant_governance_router
from app.core import persona_prompts
from app.core.policy import Plan
from app.infrastructure.redis.queue import RedisQueueHub
from .settings import Settings, get_settings
from app.infrastructure.redis.sse import RedisEventBroker, stream_redis_events
from app.infrastructure.redis.usage import get_usage
from app.core.util import job_id
from app.services.llm_engine import LLMEngine
from app.core.llm.unified import UnifiedLLMService, GeminiClientAdapter
from app.core.llm.router import OpenAIProvider, StubProvider
from app.services.flavor_architect import FlavorArchitectEngine
from app.services.receipt_vision_engine import ReceiptVisionEngine
from app.services.product_normalize import _now_iso
from app.services.model_catalog import build_models_catalog as _build_models_catalog
from app.infrastructure.db.neoeats_db import get_neoeats_db as _get_neoeats_db
from app.infrastructure.dev_helpers import (
    dev_password_hash as _dev_password_hash,
    seed_dev_users as _seed_dev_users,
    seed_dev_inventory as _seed_dev_inventory,
)


@dataclass
class AppState:
    settings: Settings
    db: DB
    redis: redis.Redis
    queuehub: RedisQueueHub
    broker: RedisEventBroker


def create_app() -> FastAPI:
    settings = get_settings()
    resolved_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.getLogger().setLevel(resolved_log_level)
    logging.getLogger("uvicorn").setLevel(resolved_log_level)
    logging.getLogger("uvicorn.error").setLevel(resolved_log_level)

    # Phase 4 — auto-mask PII in all log records
    from app.infrastructure.log_utils import PIIMaskingFilter
    logging.getLogger().addFilter(PIIMaskingFilter())

    if settings.public_mode:
        test_auth_raw = str(os.getenv("SEED_TEST_AUTH_MODE") or "").strip().lower()
        if test_auth_raw in {"1", "true", "yes", "on"}:
            raise RuntimeError("PUBLIC_MODE requires SEED_TEST_AUTH_MODE=0.")
        if not str(settings.admin_key or "").strip():
            raise RuntimeError("PUBLIC_MODE requires SEED_ADMIN_KEY to be set.")
        logging.info("PUBLIC_MODE enabled: strict CORS, hardened headers, and test routes disabled.")

    if settings.enable_legacy_x_user_id:
        logging.warning(
            "Legacy auth mode is enabled (SEED_ENABLE_LEGACY_X_USER_ID=1). "
            "This should be used only for controlled dev/test environments."
        )

    # Phase 4 — warn if api_key_pepper is empty in production/public mode
    if (settings.is_production or settings.public_mode) and not settings.api_key_pepper.strip():
        logging.warning(
            "SEED_API_KEY_PEPPER is empty in %s mode. "
            "API-key hashes are unsalted — set SEED_API_KEY_PEPPER for production security.",
            "public" if settings.public_mode else "production",
        )
    
    # Initialize metrics (StatsD client)
    if settings.metrics_enabled:
        metrics_host = os.getenv("STATSD_HOST", "localhost")
        metrics_port = int(os.getenv("STATSD_PORT", "8125"))
        init_metrics(host=metrics_host, port=metrics_port, prefix="seed_server")
    else:
        shutdown_metrics()

    # Runtime dependency check РІР‚вЂќ warns about missing packages listed in CREATED_DEPENDENCIES.md
    try:
        from .dependency_check import check_and_log

        missing = check_and_log(strict=False)
        if missing:
            logging.warning("Runtime dependencies missing: %s", ", ".join(missing))
    except Exception as e:
        logging.warning("Dependency check failed: %s", e)

    from app.infrastructure.lifespan import app_lifespan
    app = FastAPI(title="Seed Server", version="0.5.0", lifespan=app_lifespan)

    # CORS configuration
    from app.infrastructure.cors import configure_cors
    configure_cors(app, settings)

    from app.infrastructure.exception_handlers import register_exception_handlers
    register_exception_handlers(app, public_mode=settings.public_mode)

    # Lightweight admin endpoint: dependency status
    try:
        from .dependency_check import _parse_md_packages, check_and_log
    except Exception:
        _parse_md_packages = None
        check_and_log = None

    @app.get("/internal/dependencies")
    async def internal_dependencies(request: Request):
        """Return parsed dependency specs and any missing packages (lightweight).

        Security: If env var `INTERNAL_AUTH_TOKEN` is set, a matching header `X-Internal-Auth` is required.
        Otherwise access is restricted to localhost only.
        """
        if settings.public_mode:
            raise HTTPException(status_code=404, detail="not_found")
        if not _parse_md_packages or not check_and_log:
            return {"error": "dependency check not available"}

        # Security checks
        token = os.getenv("INTERNAL_AUTH_TOKEN")
        if token:
            header = request.headers.get("X-Internal-Auth") or ""
            if not hmac.compare_digest(header, token):
                raise HTTPException(status_code=401, detail="Unauthorized")
        else:
            client = request.client
            host = client.host if client else None
            if host not in ("127.0.0.1", "localhost", "::1"):
                raise HTTPException(status_code=403, detail="Forbidden")

        packages = _parse_md_packages()
        missing = check_and_log(strict=False)
        pkg_status = [{"spec": p, "installed": (p not in missing)} for p in packages]
        return {"packages": pkg_status, "missing": missing}

    # Prometheus
    if settings.metrics_enabled:
        app.mount("/metrics", make_asgi_app())

    db = DB(settings.db_path)
    db.init_schema()
    seed_defaults(db)
    if settings.seed_dev_users_on_startup and settings.dev_mode:
        _seed_dev_users(db)
    elif settings.seed_dev_users_on_startup and not settings.dev_mode:
        logging.warning(
            "SEED_SEED_DEV_USERS_ON_STARTUP=1 ignored because SEED_DEV is disabled."
        )

    r: redis.Redis = redis.from_url(settings.redis_url, decode_responses=False)
    hub = RedisQueueHub(r=r, namespace=settings.redis_namespace)
    broker = RedisEventBroker(r=r, namespace=settings.redis_namespace)
    
    # Initialize persona prompt loader
    prompts_dir = Path(__file__).parent.parent / "prompts" / "personas"
    persona_prompts.init_persona_loader(prompts_dir, dev_mode=settings.dev_mode)
    logging.info(f"Initialized persona loader from: {prompts_dir} (dev_mode={settings.dev_mode})")
    
    # Initialize production-readiness infrastructure
    try:
        from .core.feature_flags import initialize_default_flags
        from .performance_monitor import PerformanceMonitor
        from .key_management import ensure_key_audit_tables
        from .core.authz import ensure_audit_events_table
        
        # Initialize feature flags with default values
        initialize_default_flags(db)
        logging.info("Feature flags initialized")
        
        # Initialize performance monitoring database
        monitor = PerformanceMonitor(db)
        logging.info("Performance monitoring initialized")
        
        # Initialize key management audit tables
        ensure_key_audit_tables(db)
        logging.info("Key management audit tables initialized")

        # Initialize auth audit events table
        ensure_audit_events_table(db)
        logging.info("Auth audit events table initialized")
    except Exception as e:
        logging.warning(f"Failed to initialize production infrastructure: {e}")

    app.state.seed = AppState(settings=settings, db=db, redis=r, queuehub=hub, broker=broker)

    # --- Unified LLM Service ---
    llm_service = UnifiedLLMService(settings=settings)
    _gemini_api_key = os.getenv("GEMINI_API_KEY")
    if _gemini_api_key:
        try:
            from app.core.gemini_client import GeminiClient as _GClient
            _chat_model = os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-1.5-flash"
            _gc = _GClient(api_key=_gemini_api_key, default_model=_chat_model)
            llm_service.register_provider(GeminiClientAdapter(_gc, default_model=_chat_model))
        except Exception as _exc:
            logging.warning("Failed to register Gemini provider with UnifiedLLMService: %s", _exc)

    # Register OpenAI provider (available when OPENAI_API_KEY is set)
    try:
        llm_service.register_provider(OpenAIProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        ))
    except Exception as _exc:
        logging.warning("Failed to register OpenAI provider with UnifiedLLMService: %s", _exc)

    # Register Stub provider (always available — for testing / dev fallback)
    llm_service.register_provider(StubProvider())

    app.state.llm_service = llm_service

    app.state.llm_engine = LLMEngine(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        chat_model=os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-1.5-flash",
        vision_model=os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-1.5-flash",
        embedding_model=os.getenv("SEED_GEMINI_EMBED_MODEL") or "text-embedding-004",
        llm_service=llm_service,
    )
    app.state.flavor_architect_engine = FlavorArchitectEngine(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        validator_model="gemini-1.5-flash-8b",
        creative_model="gemini-2.0-flash",
    )
    app.state.receipt_vision_engine = ReceiptVisionEngine(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        vision_model=os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-1.5-flash",
    )

    # Realtime (WebSocket + Saga) wiring
    from app.infrastructure.app_wiring import wire_realtime_infrastructure

    response_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    action_router_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    saga_orchestrator, action_router, order_stream = wire_realtime_infrastructure(
        app,
        settings=settings,
        db=db,
        r=r,
        response_queue=response_queue,
        action_router_queue=action_router_queue,
    )

    async def _get_system_mode() -> str:
        row = db.fetchone("SELECT value_json FROM system_state WHERE key='system_mode'")
        if not row:
            return "normal"
        try:
            obj = json.loads(row["value_json"])
            return str(obj.get("mode") or "normal")
        except Exception:
            return "normal"

    async def _set_system_mode(mode: str) -> None:
        if mode not in ("normal", "emergency"):
            raise HTTPException(status_code=400, detail="bad mode")
        db.execute(
            "INSERT INTO system_state(key,value_json) VALUES('system_mode',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=datetime('now')",
            (json.dumps({"mode": mode}),),
        )

    def _get_plan(plan_id: str) -> Plan:
        row = db.fetchone("SELECT * FROM plans WHERE id=?", (plan_id,))
        if not row:
            row = db.fetchone("SELECT * FROM plans WHERE id=?", (settings.default_plan,))
        if not row:
            raise HTTPException(status_code=500, detail="plan not found")
        return Plan(
            id=row["id"],
            fast_daily_limit=int(row["fast_daily_limit"]),
            actions_per_minute_limit=int(row["actions_per_minute_limit"]),
            actions_monthly_limit=int(row["actions_monthly_limit"]),
            post_monthly_delay_sec=int(row["post_monthly_delay_sec"]),
            batch_priority_base=int(row["batch_priority_base"]),
            fast_priority_base=int(row["fast_priority_base"]),
            max_input_chars=int(row["max_input_chars"]),
            max_output_tokens=int(row["max_output_tokens"]),
        )

    def _get_active_plan_for_user(user_id: str) -> str:
        row = db.fetchone(
            "SELECT plan_id FROM subscriptions WHERE user_id=? AND is_active=1 ORDER BY period_end DESC LIMIT 1",
            (user_id,),
        )
        if row:
            return str(row["plan_id"])
        return settings.default_plan

    # HTTP middleware — registered AFTER cors (configure_cors above) so that
    # CORS wraps outermost.  See middleware_setup.py docstring for LIFO order.
    from app.infrastructure.middleware_setup import register_middleware
    register_middleware(app, settings=settings, db=db)

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        try:
            pong = await r.ping()
        except Exception:
            pong = False
        return {"ok": True, "redis": bool(pong), "db": True, "mode": await _get_system_mode()}

    @app.get("/")
    async def root() -> Dict[str, Any]:
        return {"name": "seed-server", "version": "0.5"}

    app.include_router(
        build_auth_router(
            app=app,
            db=db,
            redis_client=r,
            settings=settings,
            dev_password_hash=_dev_password_hash,
            seed_dev_inventory=_seed_dev_inventory,
            get_active_plan_for_user=_get_active_plan_for_user,
            get_plan=_get_plan,
            build_models_catalog=_build_models_catalog,
            job_id_factory=job_id,
        )
    )
    app.include_router(
        build_admin_router(
            db=db,
            set_system_mode=_set_system_mode,
        )
    )
    app.include_router(
        build_tenant_governance_router(
            db=db,
        )
    )
    app.include_router(
        build_jobs_router(
            db=db,
            broker=broker,
            now_iso=_now_iso,
        )
    )
    app.include_router(
        build_lessons_router(
            db=db,
            settings=settings,
            now_iso=_now_iso,
        )
    )
    app.include_router(
        build_diagnostics_router(
            db=db,
            settings=settings,
        )
    )
    app.include_router(
        build_career_router(
            db=db,
            job_id_factory=job_id,
        )
    )
    app.include_router(build_actions_saga_router(
        db=db,
        action_router=action_router,
        r=r,
        saga_orchestrator=saga_orchestrator,
        build_action_from_message=_build_action_from_message,
        get_neoeats_db=_get_neoeats_db,
    ))
    app.include_router(build_inventory_orders_vision_router(
        db=db,
        settings=settings,
        get_neoeats_db=_get_neoeats_db,
        saga_orchestrator=saga_orchestrator,
        order_stream=order_stream,
        llm_engine=app.state.llm_engine,
    ))
    app.include_router(build_neoeats_profile_router(
        db=db,
        get_neoeats_db=_get_neoeats_db,
    ))
    app.include_router(build_learning_feedback_monitoring_router(db=db))

    @app.get("/v1/stream")
    async def stream(request: Request):
        ctx = authenticate(request, db)
        sub = await broker.subscribe(ctx.user_id)

        async def gen():
            try:
                async for chunk in stream_redis_events(sub):
                    yield chunk
                    if await request.is_disconnected():
                        break
            finally:
                await broker.unsubscribe(sub)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/v1/limits")
    async def limits(request: Request):
        ctx = authenticate(request, db)
        plan_id = _get_active_plan_for_user(ctx.user_id)
        plan = _get_plan(plan_id)
        usage = await get_usage(r, settings.redis_namespace, ctx.user_id)
        return {
            "user_id": ctx.user_id,
            "plan": dataclasses.asdict(plan),
            "usage": dataclasses.asdict(usage),
        }

    app.include_router(
        build_actions_endpoint_router(
            db=db,
            settings=settings,
            r=r,
            hub=hub,
            broker=broker,
            get_plan=_get_plan,
            get_active_plan_for_user=_get_active_plan_for_user,
            get_system_mode=_get_system_mode,
        )
    )

    from app.infrastructure.router_registration import register_optional_routers
    register_optional_routers(app, settings=settings, db=db, get_neoeats_db=_get_neoeats_db)

    return app


def create_test_app() -> FastAPI:
    """Deterministic test app factory with production-equivalent route wiring."""
    return create_app()


app = create_app()


