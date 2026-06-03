from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, HTTPException, Request

from app.core.auth import authenticate
from app.infrastructure.db.sqlite import DB
from app.infrastructure.redis.sse import RedisEventBroker
from app.models.api import JobResponse


def build_jobs_router(
    *,
    db: DB,
    broker: RedisEventBroker,
    now_iso: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/jobs/{job_id}", response_model=JobResponse)
    async def get_job(job_id: str, request: Request) -> JobResponse:
        ctx = authenticate(request, db)
        row = db.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        if (row["user_id"] != ctx.user_id) and (not ctx.is_admin):
            raise HTTPException(status_code=403, detail="forbidden")

        return JobResponse(
            id=row["id"],
            user_id=row["user_id"],
            action=row["action"],
            mode=row["mode"],
            status=row["status"],
            queue_name=row["queue_name"],
            priority=int(row["priority"]),
            not_before=row["not_before"],
            provider=row["provider"],
            model=row["model"],
            persona_id_used=row["persona_id_used"] if "persona_id_used" in row.keys() else None,
            fallback_reason=row["fallback_reason"] if "fallback_reason" in row.keys() else None,
            result_text=row["result_text"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    @router.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, request: Request):
        ctx = authenticate(request, db)
        row = db.fetchone("SELECT id,user_id,status,options_json FROM jobs WHERE id=?", (job_id,))
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        if (row["user_id"] != ctx.user_id) and (not ctx.is_admin):
            raise HTTPException(status_code=403, detail="forbidden")
        if row["status"] != "queued":
            raise HTTPException(status_code=409, detail="cannot cancel")
        correlation_id = None
        try:
            opts = json.loads(row["options_json"] or "{}")
            correlation_id = (
                str(opts.get("correlation_id") or opts.get("correlationId") or "").strip() or None
            )
        except Exception:
            correlation_id = None
        db.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=?", (now_iso(), job_id))
        db.execute(
            "INSERT INTO job_events(job_id,event,data_json) VALUES(?,?,?)",
            (job_id, "cancelled", json.dumps({"correlation_id": correlation_id})),
        )
        await broker.publish(
            ctx.user_id, "job_cancelled", {"job_id": job_id, "correlation_id": correlation_id}
        )
        return {"ok": True, "job_id": job_id, "status": "cancelled"}

    return router
