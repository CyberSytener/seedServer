from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
from typing import Any, Awaitable, Callable, Dict

import redis.asyncio as redis
from fastapi import APIRouter, FastAPI, HTTPException, Request

from app.core.auth import issue_key_for_user
from app.core.authz import require_scope, resolve_auth_context
from app.infrastructure.db.sqlite import DB
from app.infrastructure.redis.usage import get_usage
from app.models.api import CreateUserRequest, CreateUserResponse, MeResponse, ModelsResponse
from app.settings import Settings


def _is_valid_public_email(value: str) -> bool:
    email = str(value or "").strip().lower()
    return "@" in email and "." in email.split("@", 1)[-1]


def _normalize_public_username(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip().lower())
    normalized = normalized.strip("_.-")
    if len(normalized) < 3:
        normalized = f"neo_{secrets.token_hex(4)}"
    return normalized[:64]


def _resolve_open_registration_identity(db: DB, username: str, email: str) -> tuple[str, str]:
    base_username = _normalize_public_username(username)
    base_email = str(email or "").strip().lower()
    if not _is_valid_public_email(base_email):
        base_email = f"{base_username}@users.neoeats.local"

    resolved_username = base_username
    resolved_email = base_email

    for attempt in range(50):
        existing = db.fetchone(
            "SELECT id, email FROM users WHERE id = ? OR email = ?",
            (resolved_username, resolved_email),
        )
        if not existing:
            return resolved_username, resolved_email

        suffix = secrets.token_hex(3)
        resolved_username = f"{base_username[:57]}_{suffix}"[:64]
        if base_email.endswith("@users.neoeats.local") or attempt > 0:
            resolved_email = f"{resolved_username}@users.neoeats.local"

    suffix = secrets.token_hex(8)
    resolved_username = f"neo_{suffix}"
    return resolved_username, f"{resolved_username}@users.neoeats.local"


def build_auth_router(
    *,
    app: FastAPI,
    db: DB,
    redis_client: redis.Redis,
    settings: Settings,
    dev_password_hash: Callable[[str, str], str],
    seed_dev_inventory: Callable[[FastAPI, str], Awaitable[None]],
    get_active_plan_for_user: Callable[[str], str],
    get_plan: Callable[[str], Any],
    build_models_catalog: Callable[[Settings], list[Any]],
    job_id_factory: Callable[[str], str],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/auth/login")
    async def auth_login(request: Request):
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_payload")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid_payload")

        username = str(payload.get("username") or payload.get("email") or "").strip()
        password = str(payload.get("password") or "").strip()
        if not username or not password:
            raise HTTPException(status_code=401, detail="invalid_credentials")

        user = db.fetchone(
            "SELECT id, email, meta_json, is_banned FROM users WHERE id = ? OR email = ?",
            (username, username),
        )
        if not user:
            raise HTTPException(status_code=401, detail="invalid_credentials")

        if int(user["is_banned"] or 0) == 1:
            raise HTTPException(status_code=403, detail="banned")

        meta: Dict[str, Any] = {}
        try:
            meta = json.loads(user["meta_json"] or "{}")
        except Exception:
            meta = {}

        stored_hash = str(meta.get("password_hash") or "")
        if not stored_hash:
            raise HTTPException(status_code=401, detail="invalid_credentials")

        provided_hash = dev_password_hash(str(user["id"]), password)
        if not hmac.compare_digest(stored_hash, provided_hash):
            raise HTTPException(status_code=401, detail="invalid_credentials")

        access_token = issue_key_for_user(db, str(user["id"]))

        if os.getenv("SEED_DEV_INVENTORY_SEED_ON_LOGIN", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            await seed_dev_inventory(app, str(user["id"]))

        return {
            "user": {
                "userId": str(user["id"]),
                "id": str(user["id"]),
                "name": str(meta.get("username") or user["id"]),
                "email": user["email"],
            },
            "accessToken": access_token,
            "refreshToken": None,
            "tokenType": "Bearer",
        }

    @router.post("/api/v1/auth/register")
    async def auth_register(request: Request):
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_payload")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid_payload")

        raw_username = str(payload.get("username") or "").strip()
        raw_email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "").strip()

        if not password:
            password = secrets.token_urlsafe(18)

        username_seed = raw_username or raw_email.split("@", 1)[0] or "neo_user"
        username, email = _resolve_open_registration_identity(db, username_seed, raw_email)
        requested_email = raw_email if _is_valid_public_email(raw_email) else None

        meta_json = json.dumps(
            {
                "username": username,
                "password_hash": dev_password_hash(username, password),
                "open_registration": True,
                "email_confirmed": True,
                "requested_email": requested_email,
            },
            ensure_ascii=False,
        )

        try:
            db.execute(
                "INSERT INTO users(id,email,meta_json,is_admin,is_banned) VALUES(?,?,?,0,0)",
                (username, email, meta_json),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="user_exists")

        access_token = issue_key_for_user(db, username)
        return {
            "user": {
                "userId": username,
                "id": username,
                "name": username,
                "email": email,
            },
            "accessToken": access_token,
            "refreshToken": None,
            "tokenType": "Bearer",
        }

    @router.post("/api/v1/auth/refresh")
    async def auth_refresh(request: Request):
        ctx = require_scope(request, db, "runs:write")
        access_token = issue_key_for_user(db, ctx.user_id)
        return {"accessToken": access_token, "tokenType": "Bearer"}

    @router.post("/api/v1/auth/logout")
    async def auth_logout(request: Request):
        ctx = resolve_auth_context(request, db, required=True)
        if ctx is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        return {"ok": True, "user_id": ctx.user_id}

    @router.post("/v1/users", response_model=CreateUserResponse)
    async def create_user(req: CreateUserRequest, request: Request) -> CreateUserResponse:
        logger = logging.getLogger("uvicorn")
        logger.info(
            f"[CREATE_USER] Request: user_id='{req.user_id}', is_admin={req.is_admin}, email='{req.email}'"
        )

        requesting_admin_privileges = req.is_admin
        if requesting_admin_privileges:
            logger.info(
                f"[CREATE_USER] Admin privileges requested (is_admin={req.is_admin}), checking admin key"
            )
            if not settings.admin_key:
                logger.warning(
                    "[CREATE_USER] Admin operation requested but SEED_ADMIN_KEY is not configured"
                )
                raise HTTPException(status_code=403, detail="admin provisioning disabled")
            admin_key = request.headers.get("X-Admin-Key") or ""
            if not hmac.compare_digest(admin_key, settings.admin_key):
                logger.warning("[CREATE_USER] Admin key missing or invalid for admin operation")
                raise HTTPException(
                    status_code=403, detail="admin key required for admin operations"
                )
        else:
            logger.info("[CREATE_USER] Regular user creation, no admin key required")

        uid = req.user_id or job_id_factory("usr")
        email = (req.email or "").strip() or None
        meta_json = json.dumps(req.meta or {}, ensure_ascii=False)
        is_admin = 1 if req.is_admin else 0

        if email:
            erow = db.fetchone("SELECT id FROM users WHERE email=?", (email,))
            if erow and str(erow["id"]) != uid:
                raise HTTPException(status_code=409, detail="email already used")

        try:
            db.execute(
                "INSERT INTO users(id,email,meta_json,is_admin) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET email=excluded.email, meta_json=excluded.meta_json, is_admin=excluded.is_admin",
                (uid, email, meta_json, is_admin),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="conflict")

        api_key = issue_key_for_user(db, uid)
        return CreateUserResponse(user_id=uid, api_key=api_key)

    @router.get("/v1/me", response_model=MeResponse)
    async def get_me(request: Request) -> MeResponse:
        ctx = resolve_auth_context(request, db, required=True)
        if ctx is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        credits_daily_limit = 0
        credits_balance = 0
        try:
            active_plan = get_plan(get_active_plan_for_user(ctx.user_id))
            credits_daily_limit = max(0, int(active_plan.fast_daily_limit))
            usage = await get_usage(redis_client, settings.redis_namespace, ctx.user_id)
            credits_balance = max(0, credits_daily_limit - int(usage.fast_used_today))
        except Exception:
            credits_daily_limit = 0
            credits_balance = 0

        row = db.fetchone(
            "SELECT id, email, is_admin, meta_json FROM users WHERE id=?", (ctx.user_id,)
        )
        if not row:
            if ctx.auth_type == "test_token" and settings.test_auth_mode:
                return MeResponse(
                    user_id=ctx.user_id,
                    is_admin=ctx.is_admin,
                    email=None,
                    meta={
                        "role": ctx.role,
                        "scopes": sorted(ctx.scopes),
                        "test_mode": True,
                    },
                    creditsBalance=credits_balance,
                    creditsDailyLimit=credits_daily_limit,
                )
            if ctx.user_id == "admin" and ctx.is_admin:
                return MeResponse(
                    user_id="admin",
                    is_admin=True,
                    email=None,
                    meta={},
                    creditsBalance=credits_balance,
                    creditsDailyLimit=credits_daily_limit,
                )
            raise HTTPException(status_code=404, detail="user_not_found")

        meta: Dict[str, Any] = {}
        try:
            parsed = json.loads(row["meta_json"] or "{}")
            meta = parsed if isinstance(parsed, dict) else {}
        except Exception:
            meta = {}

        return MeResponse(
            user_id=str(row["id"]),
            is_admin=bool(row["is_admin"]),
            email=row["email"],
            meta=meta,
            creditsBalance=credits_balance,
            creditsDailyLimit=credits_daily_limit,
        )

    @router.get("/v1/auth/providers")
    async def get_auth_providers() -> Dict[str, Any]:
        jwt_enabled = bool((os.getenv("JWT_SECRET_KEY") or "").strip())
        return {
            "default": "api_key",
            "providers": [
                {
                    "id": "api_key",
                    "enabled": True,
                    "description": "Authorization: Bearer <api_key>",
                },
                {
                    "id": "admin_key",
                    "enabled": bool(settings.admin_key),
                    "description": "X-Admin-Key header for admin operations",
                },
                {
                    "id": "jwt",
                    "enabled": jwt_enabled,
                    "description": "Authorization: Bearer <jwt_token>",
                },
                {
                    "id": "legacy_x_user_id",
                    "enabled": bool(settings.enable_legacy_x_user_id),
                    "description": "X-User-ID legacy mode",
                },
            ],
        }

    @router.get("/v1/models", response_model=ModelsResponse)
    async def get_models(request: Request) -> ModelsResponse:
        require_scope(request, db, "runs:read")

        if settings.default_provider_fast == "gemini":
            default_fast_model = settings.gemini_model_fast
        elif settings.default_provider_fast == "openai":
            default_fast_model = settings.openai_model_fast
        else:
            default_fast_model = settings.gemini_model_fast or settings.openai_model_fast

        if settings.default_provider_batch == "gemini":
            default_batch_model = settings.gemini_model_batch
        elif settings.default_provider_batch == "openai":
            default_batch_model = settings.openai_model_batch
        else:
            default_batch_model = settings.gemini_model_batch or settings.openai_model_batch

        return ModelsResponse(
            models=build_models_catalog(settings),
            defaultFastModel=default_fast_model,
            defaultBatchModel=default_batch_model,
        )

    return router
