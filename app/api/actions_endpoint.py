from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Awaitable, Callable, Dict

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException, Header, Request

from app.core.auth import authenticate
from app.core import persona_prompts
from app.core.llm.router import ProviderError, execute_action
from app.core.metrics import JOBS_CREATED, QUEUE_DEPTH, SCHEDULED_DEPTH
from app.core.policy import Plan, decide_policy
from app.core.rate_limit import check_rate_limits
from app.core.util import job_id
from app.infrastructure.db.sqlite import DB
from app.infrastructure.redis.queue import RedisQueueHub
from app.infrastructure.redis.sse import RedisEventBroker
from app.infrastructure.redis.usage import bump_usage, get_usage
from app.models.api import (
    ActionRequest,
    ActionResponse,
    JobStatus,
    PersonaInfo,
    PersonasResponse,
)
from app.services.product_normalize import _now_iso
from app.settings import Settings


def build_actions_endpoint_router(
    *,
    db: DB,
    settings: Settings,
    r: redis.Redis,
    hub: RedisQueueHub,
    broker: RedisEventBroker,
    get_plan: Callable[[str], Plan],
    get_active_plan_for_user: Callable[[str], str],
    get_system_mode: Callable[[], Awaitable[str]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/actions", response_model=ActionResponse)
    async def actions(req: ActionRequest, request: Request) -> ActionResponse:
        ctx = authenticate(request, db)

        input_text = req.text or ""
        options: Dict[str, Any] = dict(req.options or {})
        action = req.action.value if hasattr(req.action, "value") else str(req.action)
        persona_id_requested = req.persona_id or None

        header_idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
        body_idempotency_key = str(req.idempotency_key or "").strip()
        options_idempotency_key = str(
            options.get("idempotency_key")
            or options.get("idempotencyKey")
            or ""
        ).strip()
        idempotency_key = header_idempotency_key or body_idempotency_key or options_idempotency_key
        if not idempotency_key:
            idempotency_key = None
        elif len(idempotency_key) > 256:
            raise HTTPException(status_code=400, detail="idempotency key too long")

        options_for_hash = dict(options)
        options_for_hash.pop("idempotency_key", None)
        options_for_hash.pop("idempotencyKey", None)
        input_hash = hashlib.sha256(
            json.dumps(
                {
                    "user_id": ctx.user_id,
                    "action": action,
                    "text": input_text,
                    "options": options_for_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        def _action_response_from_row(row: sqlite3.Row) -> ActionResponse:
            return ActionResponse(
                job_id=row["id"],
                mode=row["mode"],
                status=row["status"],
                result_text=row["result_text"],
                error_message=row["error_message"],
                persona_id_used=row["persona_id_used"] if "persona_id_used" in row.keys() else None,
                fallback_reason=row["fallback_reason"] if "fallback_reason" in row.keys() else None,
            )

        if idempotency_key:
            existing = db.fetchone(
                """
                SELECT id, mode, status, result_text, error_message, persona_id_used, fallback_reason, input_hash
                FROM jobs
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (ctx.user_id, idempotency_key),
            )
            if existing:
                existing_hash = str(existing["input_hash"] or "")
                if existing_hash and existing_hash != input_hash:
                    raise HTTPException(status_code=409, detail="idempotency key already used with different payload")
                return _action_response_from_row(existing)

        correlation_id = (
            (request.headers.get("X-Correlation-ID") or "").strip()
            or (request.headers.get("X-Request-ID") or "").strip()
            or str(options.get("correlation_id") or options.get("correlationId") or "").strip()
            or str(uuid.uuid4())
        )
        options["correlation_id"] = correlation_id
        
        # Resolve persona using file-based loader
        persona_result = persona_prompts.get_persona_prompt(persona_id_requested)
        persona_id_used = persona_result.persona_id_used
        fallback_reason = persona_result.fallback_reason

        plan_id = get_active_plan_for_user(ctx.user_id)
        plan = get_plan(plan_id)

        # Enforce plan defaults unless caller overrides.
        options.setdefault("max_output_tokens", plan.max_output_tokens)

        if len(input_text) > plan.max_input_chars:
            raise HTTPException(status_code=413, detail="input too large")

        client_ip = request.client.host if request.client else "unknown"
        rate = await check_rate_limits(
            r=r,
            namespace=settings.redis_namespace,
            user_id=ctx.user_id,
            ip=client_ip,
            soft_rpm=plan.actions_per_minute_limit,
            hard_rpm=settings.hard_rpm_default,
            hard_rps=settings.hard_rps_default,
        )

        usage = await get_usage(r, settings.redis_namespace, ctx.user_id)
        urow = db.fetchone("SELECT abuse_score FROM users WHERE id=?", (ctx.user_id,))
        abuse = int(urow["abuse_score"]) if urow else 0

        system_mode = "emergency" if settings.emergency_mode else await get_system_mode()

        pol = decide_policy(
            plan=plan,
            usage=usage,
            action=action,
            input_len=len(input_text),
            abuse_score=abuse,
            system_mode=system_mode,
            rate_delay_sec=rate.delay_sec,
        )

        jid = job_id()
        created_at = _now_iso()
        not_before_iso = pol.not_before.isoformat() if pol.not_before else None

        try:
            db.execute(
                """
                INSERT INTO jobs(id,user_id,action,mode,status,idempotency_key,input_hash,dedup_of_job_id,priority,not_before,queue_name,provider,model,persona_id_used,fallback_reason,input_text,options_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    jid,
                    ctx.user_id,
                    action,
                    pol.mode,
                    "queued",
                    idempotency_key,
                    input_hash,
                    None,
                    int(pol.priority),
                    not_before_iso,
                    pol.queue_name,
                    str(options.get("provider") or "auto"),
                    str(options.get("model") or "auto"),
                    persona_id_used,
                    fallback_reason,
                    input_text,
                    json.dumps(options, ensure_ascii=False),
                    created_at,
                ),
            )
        except sqlite3.IntegrityError:
            if not idempotency_key:
                raise
            existing = db.fetchone(
                """
                SELECT id, mode, status, result_text, error_message, persona_id_used, fallback_reason, input_hash
                FROM jobs
                WHERE user_id = ? AND idempotency_key = ?
                """,
                (ctx.user_id, idempotency_key),
            )
            if existing:
                existing_hash = str(existing["input_hash"] or "")
                if existing_hash and existing_hash != input_hash:
                    raise HTTPException(status_code=409, detail="idempotency key already used with different payload")
                return _action_response_from_row(existing)
            raise

        await bump_usage(
            r,
            settings.redis_namespace,
            ctx.user_id,
            inc_actions=1,
            inc_fast=1 if pol.mode == "fast" else 0,
        )

        # Inline fast execution (optional): good UX + reduces queue churn.
        if pol.mode == "fast" and pol.not_before is None and settings.fast_timeout_sec > 0 and system_mode != "emergency":
            try:
                db.execute(
                    "UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'",
                    (_now_iso(), jid),
                )
                db.execute(
                    "INSERT INTO job_events(job_id,event,data_json) VALUES(?,?,?)",
                    (jid, "running", json.dumps({"worker": "inline", "correlation_id": correlation_id})),
                )
                await broker.publish(ctx.user_id, "job_running", {"job_id": jid, "worker": "inline", "correlation_id": correlation_id})

                try:
                    start_time = time.perf_counter()
                    res = await asyncio.wait_for(execute_action(action, input_text, options, pol.mode, persona_id_requested), timeout=float(settings.fast_timeout_sec))
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    
                    # Structured logging
                    logging.info(
                        "Action executed",
                        extra={
                            "request_id": jid,
                            "user_id": ctx.user_id,
                            "action": action,
                            "mode": pol.mode,
                            "persona_id_requested": persona_id_requested,
                            "persona_id_used": res.persona_id_used,
                            "fallback_reason": fallback_reason,
                            "provider": res.provider,
                            "model": res.model,
                            "duration_ms": duration_ms,
                            "correlation_id": correlation_id,
                            "status": "ok",
                        }
                    )
                except asyncio.TimeoutError:
                    # revert to queued and enqueue
                    db.execute(
                        "UPDATE jobs SET status='queued', started_at=NULL WHERE id=?",
                        (jid,),
                    )
                else:
                    db.execute(
                        """
                        UPDATE jobs
                        SET status='done', provider=?, model=?, persona_id_used=?,
                            tokens_in_actual=?, tokens_out_actual=?, cost_usd_actual=?,
                            result_text=?, finished_at=?
                        WHERE id=?
                        """,
                        (
                            res.provider,
                            res.model,
                            res.persona_id_used,
                            res.tokens_in,
                            res.tokens_out,
                            float(res.cost_usd),
                            res.text,
                            _now_iso(),
                            jid,
                        ),
                    )
                    db.execute(
                        "INSERT INTO job_events(job_id,event,data_json) VALUES(?,?,?)",
                        (jid, "done", json.dumps({"correlation_id": correlation_id})),
                    )
                    await broker.publish(ctx.user_id, "job_done", {"job_id": jid, "mode": pol.mode, "queue": pol.queue_name, "correlation_id": correlation_id})
                    return ActionResponse(job_id=jid, mode=pol.mode, status=JobStatus.done, result_text=res.text, persona_id_used=res.persona_id_used, fallback_reason=fallback_reason)

            except ProviderError as e:
                # Fail fast (real provider misconfigured)
                logging.error(
                    "Action failed - provider error",
                    extra={
                        "request_id": jid,
                        "user_id": ctx.user_id,
                        "action": action,
                        "persona_id_requested": persona_id_requested,
                        "persona_id_used": persona_id_used,
                        "fallback_reason": fallback_reason,
                        "correlation_id": correlation_id,
                        "status": "error",
                        "error": str(e)[:200],
                    }
                )
                db.execute(
                    "UPDATE jobs SET status='failed', error_code=?, error_message=?, finished_at=? WHERE id=?",
                    ("provider_error", str(e)[:2000], _now_iso(), jid),
                )
                db.execute(
                    "INSERT INTO job_events(job_id,event,data_json) VALUES(?,?,?)",
                    (jid, "failed", json.dumps({"correlation_id": correlation_id})),
                )
                await broker.publish(ctx.user_id, "job_failed", {"job_id": jid, "error": str(e)[:300], "correlation_id": correlation_id})
                return ActionResponse(job_id=jid, mode=pol.mode, status=JobStatus.failed, error_message=str(e), persona_id_used=persona_id_used, fallback_reason=fallback_reason)
            except Exception as e:
                logging.error(
                    "Action failed - general error",
                    extra={
                        "request_id": jid,
                        "user_id": ctx.user_id,
                        "action": action,
                        "persona_id_requested": persona_id_requested,
                        "persona_id_used": persona_id_used,
                        "fallback_reason": fallback_reason,
                        "correlation_id": correlation_id,
                        "status": "error",
                        "error": str(e)[:200],
                    }
                )
                db.execute(
                    "UPDATE jobs SET status='failed', error_code=?, error_message=?, finished_at=? WHERE id=?",
                    ("error", str(e)[:2000], _now_iso(), jid),
                )
                db.execute(
                    "INSERT INTO job_events(job_id,event,data_json) VALUES(?,?,?)",
                    (jid, "failed", json.dumps({"correlation_id": correlation_id})),
                )
                await broker.publish(ctx.user_id, "job_failed", {"job_id": jid, "error": str(e)[:300], "correlation_id": correlation_id})
                return ActionResponse(job_id=jid, mode=pol.mode, status=JobStatus.failed, error_message=str(e), persona_id_used=persona_id_used, fallback_reason=fallback_reason)

        # Enqueue (batch/hybrid or fast timeout fallback)
        if pol.not_before is not None:
            await hub.schedule(
                queue_name=pol.queue_name,
                job_id=jid,
                priority=int(pol.priority),
                run_at_ts=float(pol.not_before.timestamp()),
            )
        else:
            await hub.enqueue(queue_name=pol.queue_name, job_id=jid, priority=int(pol.priority))

        if settings.metrics_enabled:
            JOBS_CREATED.labels(mode=pol.mode, queue=pol.queue_name).inc()
            try:
                QUEUE_DEPTH.labels(queue=pol.queue_name).set(await hub.queue_depth(pol.queue_name))
                SCHEDULED_DEPTH.set(await hub.scheduled_depth())
            except Exception:
                logging.debug("Suppressed exception", exc_info=True)
        await broker.publish(ctx.user_id, "job_queued", {"job_id": jid, "mode": pol.mode, "queue": pol.queue_name, "correlation_id": correlation_id})

        return ActionResponse(job_id=jid, mode=pol.mode, status=JobStatus.queued, persona_id_used=persona_id_used, fallback_reason=fallback_reason)

    @router.get("/v1/personas", response_model=PersonasResponse)
    async def list_personas(request: Request, authorization: str = Header(None)) -> PersonasResponse:
        """
        List all available personas with metadata.
        
        Returns metadata for each persona including name, description, tags,
        and file modification timestamp. Does not include full prompt text.
        
        Authentication: OPTIONAL - Public endpoint.
        If Authorization header is present, it must be valid.
        """
        # Public without auth; strict validation when auth header is supplied.
        if authorization:
            authenticate(request, db)
        
        # Get all persona metadata
        metadata_list = persona_prompts.list_all_metadata()
        
        # Convert to response model
        personas = [
            PersonaInfo(
                id=meta.id,
                name=meta.name,
                description=meta.description,
                tags=meta.tags,
                prompt_source=meta.prompt_source,
                prompt_updated_at=meta.prompt_updated_at,
                is_default=meta.is_default,
            )
            for meta in metadata_list
        ]
        
        default_persona_id = persona_prompts.get_default_persona_id()
        
        return PersonasResponse(
            personas=personas,
            default_persona_id=default_persona_id,
        )

    return router
