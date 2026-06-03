from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Environment profile
    environment: str
    is_production: bool
    public_mode: bool

    # Core
    db_path: str
    default_plan: str
    emergency_mode: bool

    # UX / I/O
    fast_timeout_sec: int
    max_input_chars_default: int
    max_output_chars_default: int

    # Auth
    admin_key: str
    api_key_pepper: str
    cache_ttl_days: int
    enable_legacy_x_user_id: bool

    # Redis (queues, rate limits, counters, SSE pubsub)
    redis_url: str
    redis_namespace: str

    # Embedded background processes (dev)
    embedded_workers: bool
    embedded_scheduler: bool
    embedded_worker_queues: str

    # Providers / router
    default_provider_fast: str
    default_provider_batch: str

    openai_api_key: str
    openai_base_url: str
    openai_model_fast: str
    openai_model_batch: str

    gemini_api_key: str
    gemini_base_url: str
    gemini_model_fast: str
    gemini_model_batch: str

    # JWT
    jwt_audience: str
    jwt_issuer: str

    # Rate limits (hard safety rail)
    hard_rpm_default: int
    hard_rps_default: int

    # Metrics
    metrics_enabled: bool
    log_level: str

    # CORS
    cors_dev_mode: bool
    cors_origins: str
    allowed_origins: str
    
    # Personas
    dev_mode: bool
    
    # Optimization test mode (for compact output and parsing)
    optimize_mode: bool
    
    # Prompt testing mode (for A/B testing different prompts)
    prompt_test_mode: bool

    # HTTP hardening
    max_request_body_bytes: int
    
    # Parser version (baseline or v2 for performance testing)
    parser_version: str
    
    # LLM Provider Feature Flags
    enable_openai: bool
    enable_gemini: bool
    enable_stub: bool

    # Dev safety toggles
    seed_dev_users_on_startup: bool

    # Unified auth / simulation
    test_auth_mode: bool
    test_auth_default_role: str
    test_auth_default_scopes: str

    # Phase 7 — Agent sessions
    agent_session_ttl_seconds: int
    sandbox_enabled: bool
    # P0-20 — Sub-agent nesting
    agent_max_nesting_depth: int
    # P0-21 — Parallel sub-agents
    agent_max_parallel_children: int
    # P0-28 — Sandbox egress proxy
    sandbox_egress_proxy_url: str
    sandbox_egress_allowlist: str


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in ("1", "true", "yes", "y", "on"):
        return True
    if val in ("0", "false", "no", "n", "off"):
        return False
    return default


import logging as _logging


def _resolve_admin_key(is_production: bool, public_mode: bool) -> str:
    key = os.getenv("SEED_ADMIN_KEY", "")
    if (is_production or public_mode) and not key:
        _logging.warning("SEED_ADMIN_KEY is empty — admin endpoints will be inaccessible")
    return key


def _resolve_api_key_pepper(is_production: bool, public_mode: bool) -> str:
    pepper = os.getenv("SEED_API_KEY_PEPPER", "")
    if (is_production or public_mode) and not pepper:
        raise RuntimeError(
            "SEED_API_KEY_PEPPER must be set in production/public mode. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if not pepper:
        _logging.warning("SEED_API_KEY_PEPPER is not set — API key security reduced")
    return pepper


def _get_environment() -> str:
    raw = (os.getenv("SEED_ENV") or os.getenv("SEED_PROFILE") or "development").strip().lower()
    aliases = {
        "prod": "production",
        "production": "production",
        "dev": "development",
        "development": "development",
        "test": "test",
        "testing": "test",
        "ci": "test",
    }
    return aliases.get(raw, "development")


def get_settings() -> Settings:
    environment = _get_environment()
    is_production = environment == "production"
    public_mode = _get_bool("PUBLIC_MODE", False)

    enable_legacy_x_user_id = _get_bool("SEED_ENABLE_LEGACY_X_USER_ID", False)
    if is_production or public_mode:
        # Hard-disable legacy header auth in production profile.
        enable_legacy_x_user_id = False

    cors_dev_mode = _get_bool("SEED_DEV_CORS", False)
    if is_production or public_mode:
        # Explicit dev-only behavior.
        cors_dev_mode = False

    dev_mode = _get_bool("SEED_DEV", environment in {"development", "test"})
    if public_mode:
        dev_mode = False

    seed_dev_users_on_startup = _get_bool("SEED_SEED_DEV_USERS_ON_STARTUP", False)
    if is_production or public_mode:
        seed_dev_users_on_startup = False

    test_auth_mode = _get_bool("SEED_TEST_AUTH_MODE", False)
    if environment not in {"development", "test"}:
        test_auth_mode = False
    if is_production or public_mode:
        test_auth_mode = False

    allowed_origins = (os.getenv("ALLOWED_ORIGINS") or "").strip()
    seed_cors_origins = (os.getenv("SEED_CORS_ORIGINS") or "").strip()
    cors_origins = allowed_origins or seed_cors_origins
    if public_mode and not cors_origins:
        cors_origins = "https://neoeats.no,https://www.neoeats.no"

    log_level = (os.getenv("SEED_LOG_LEVEL") or "INFO").strip().upper() or "INFO"
    if public_mode and log_level in {"DEBUG", "TRACE", "NOTSET"}:
        log_level = "INFO"

    prompt_test_mode = _get_bool("SEED_PROMPT_TEST_MODE", False)
    if public_mode:
        prompt_test_mode = False

    max_request_body_bytes = _get_int("SEED_MAX_REQUEST_BODY_BYTES", 10 * 1024 * 1024)
    if max_request_body_bytes <= 0:
        max_request_body_bytes = 10 * 1024 * 1024

    return Settings(
        environment=environment,
        is_production=is_production,
        public_mode=public_mode,
        db_path=os.getenv("SEED_DB_PATH", "./seed.db"),
        default_plan=os.getenv("SEED_DEFAULT_PLAN", "free"),
        emergency_mode=_get_bool("SEED_EMERGENCY_MODE", False),
        fast_timeout_sec=_get_int("SEED_FAST_TIMEOUT_SEC", 3),
        max_input_chars_default=_get_int("SEED_MAX_INPUT_CHARS_DEFAULT", 12000),
        max_output_chars_default=_get_int("SEED_MAX_OUTPUT_CHARS_DEFAULT", 20000),
        admin_key=_resolve_admin_key(is_production, public_mode),
        api_key_pepper=_resolve_api_key_pepper(is_production, public_mode),
        cache_ttl_days=_get_int("SEED_CACHE_TTL_DAYS", 7),
        enable_legacy_x_user_id=enable_legacy_x_user_id,
        redis_url=os.getenv("SEED_REDIS_URL", "redis://localhost:6379/0"),
        redis_namespace=os.getenv("SEED_REDIS_NAMESPACE", "seed"),
        embedded_workers=_get_bool("SEED_EMBEDDED_WORKERS", False),
        embedded_scheduler=_get_bool("SEED_EMBEDDED_SCHEDULER", False),
        embedded_worker_queues=os.getenv("SEED_EMBEDDED_WORKER_QUEUES", "q_fast,q_batch,q_low"),
        default_provider_fast=os.getenv("SEED_DEFAULT_PROVIDER_FAST", "gemini"),
        default_provider_batch=os.getenv("SEED_DEFAULT_PROVIDER_BATCH", "gemini"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_base_url=os.getenv("SEED_OPENAI_BASE_URL", "https://api.openai.com"),
        openai_model_fast=os.getenv("SEED_OPENAI_MODEL_FAST", "gpt-4.1-mini"),
        openai_model_batch=os.getenv("SEED_OPENAI_MODEL_BATCH", "gpt-4.1"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_base_url=os.getenv("SEED_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"),
        gemini_model_fast=os.getenv("SEED_GEMINI_MODEL_FAST", "gemini-2.0-flash"),
        gemini_model_batch=os.getenv("SEED_GEMINI_MODEL_BATCH", "gemini-2.5-pro"),
        jwt_audience=os.getenv("SEED_JWT_AUDIENCE", "seed-server"),
        jwt_issuer=os.getenv("SEED_JWT_ISSUER", "seed-server"),
        hard_rpm_default=_get_int("SEED_HARD_RPM_DEFAULT", 240),
        hard_rps_default=_get_int("SEED_HARD_RPS_DEFAULT", 20),
        metrics_enabled=_get_bool("SEED_METRICS_ENABLED", True),
        log_level=log_level,
        cors_dev_mode=cors_dev_mode,
        cors_origins=cors_origins,
        allowed_origins=allowed_origins,
        dev_mode=dev_mode,
        optimize_mode=_get_bool("SEED_OPTIMIZE_MODE", False),
        prompt_test_mode=prompt_test_mode,
        max_request_body_bytes=max_request_body_bytes,
        parser_version=os.getenv("SEED_PARSER_VERSION", "baseline"),
        enable_openai=_get_bool("SEED_ENABLE_OPENAI", True),
        enable_gemini=_get_bool("SEED_ENABLE_GEMINI", True),
        enable_stub=_get_bool("SEED_ENABLE_STUB", True),
        seed_dev_users_on_startup=seed_dev_users_on_startup,
        # Opt-in only; additionally restricted to development/test profiles.
        test_auth_mode=test_auth_mode,
        test_auth_default_role=os.getenv("SEED_TEST_AUTH_DEFAULT_ROLE", "developer"),
        test_auth_default_scopes=os.getenv(
            "SEED_TEST_AUTH_DEFAULT_SCOPES",
            "runs:read,runs:write,modules:read,flows:read,catalog:read,blueprints:write",
        ),
        agent_session_ttl_seconds=_get_int("SEED_AGENT_SESSION_TTL_SECONDS", 3600),
        sandbox_enabled=_get_bool("SEED_SANDBOX_ENABLED", False),
        agent_max_nesting_depth=_get_int("SEED_AGENT_MAX_NESTING_DEPTH", 3),
        agent_max_parallel_children=_get_int("SEED_AGENT_MAX_PARALLEL_CHILDREN", 5),
        sandbox_egress_proxy_url=os.getenv(
            "SEED_SANDBOX_EGRESS_PROXY_URL", "http://sandbox_egress_proxy:3128"
        ),
        sandbox_egress_allowlist=os.getenv(
            "SEED_SANDBOX_EGRESS_ALLOWLIST",
            "github.com,api.github.com,raw.githubusercontent.com,codeload.github.com",
        ),
    )
