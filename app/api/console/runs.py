from __future__ import annotations
import logging

import asyncio
from typing import Any, AsyncIterator, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.console.utils import (
    RunCreateRequest,
    _CONTEXT_ROOTS,
    _create_flow_run,
    _create_module_run,
    _enforce_real_run_gate,
    _flow_run_detail,
    _flow_run_summary,
    _get_console_mode_runs,
    _get_run_store,
    _module_run_detail,
    _module_run_summary,
    _require_scope,
    _sse_event,
    module_registry,
)


logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/runs")
async def create_run(run_req: RunCreateRequest, request: Request) -> Dict[str, Any]:
    ctx = _require_scope(request, "runs:write")
    if run_req.mode == "real":
        profile_id = _enforce_real_run_gate(request, ctx=ctx, run_req=run_req)
        run_req.provider_profile = profile_id

    target_type = run_req.target.type
    if target_type == "module":
        return await _create_module_run(run_req, request)
    if target_type == "flow":
        return await _create_flow_run(run_req, request, auth_ctx=ctx)
    raise HTTPException(status_code=400, detail="unsupported_target_type")


@router.get("/runs")
async def list_runs(
    request: Request,
    target_type: Optional[Literal["module", "flow"]] = None,
    target_id: Optional[str] = None,
    blueprint_name: Optional[str] = None,
    status: Optional[Literal["running", "done", "failed", "stopped"]] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    _require_scope(request, "runs:read")

    safe_limit = max(1, min(int(limit), 500))
    orchestrator = getattr(request.app.state, "saga_orchestrator", None)

    mode_entries = list(_get_console_mode_runs(request).values())
    mode_summaries = await asyncio.gather(
        *[_module_run_summary(entry, orchestrator) for entry in mode_entries]
    ) if mode_entries else []

    run_store = _get_run_store(request)
    try:
        flow_records = await run_store.list_runs(limit=safe_limit)
    except Exception:
        flow_records = []
    flow_summaries = [_flow_run_summary(record) for record in flow_records]

    runs = [*mode_summaries, *flow_summaries]

    effective_target_id = target_id or blueprint_name
    effective_target_type = target_type
    if blueprint_name and not target_type:
        effective_target_type = "flow"

    if effective_target_type:
        runs = [item for item in runs if item.get("target_type") == effective_target_type]
    if effective_target_id:
        runs = [item for item in runs if item.get("target_id") == effective_target_id]
    if status:
        runs = [item for item in runs if item.get("status") == status]

    runs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"runs": runs[:safe_limit]}


@router.get("/runs/module-stats")
async def list_module_stats(
    request: Request,
    target_id: Optional[str] = None,
    blueprint_name: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    _require_scope(request, "runs:read")

    run_store = _get_run_store(request)
    safe_limit = max(1, min(int(limit), 500))
    try:
        records = await run_store.list_runs(
            blueprint_name=target_id or blueprint_name or None,
            limit=safe_limit,
        )
    except Exception:
        records = []

    stats: Dict[str, Dict[str, Any]] = {}
    for record in records:
        seen_in_run: set[str] = set()
        trace = record.execution_trace if isinstance(record.execution_trace, list) else []
        for entry in trace:
            if not isinstance(entry, dict):
                continue
            module = str(entry.get("block") or "").strip()
            if not module:
                continue
            bucket = stats.setdefault(
                module,
                {
                    "block": module,
                    "run_count": 0,
                    "step_count": 0,
                    "elapsed_sum": 0.0,
                    "elapsed_count": 0,
                    "last_seen": None,
                },
            )
            bucket["step_count"] += 1
            elapsed = entry.get("elapsed_sec")
            if isinstance(elapsed, (int, float)):
                bucket["elapsed_sum"] += float(elapsed)
                bucket["elapsed_count"] += 1
            if module not in seen_in_run:
                bucket["run_count"] += 1
                seen_in_run.add(module)

            record_created = record.created_at.isoformat() if record.created_at else None
            if record_created and (
                bucket["last_seen"] is None or str(bucket["last_seen"]) < record_created
            ):
                bucket["last_seen"] = record_created

    modules = []
    for module, bucket in stats.items():
        avg_elapsed = (
            round(bucket["elapsed_sum"] / float(bucket["elapsed_count"]), 4)
            if bucket["elapsed_count"]
            else 0.0
        )
        modules.append(
            {
                "block": module,
                "run_count": int(bucket["run_count"]),
                "step_count": int(bucket["step_count"]),
                "avg_elapsed_sec": avg_elapsed,
                "last_seen": bucket["last_seen"],
            }
        )

    modules.sort(key=lambda item: int(item.get("step_count") or 0), reverse=True)
    return {"total_runs": len(records), "modules": modules}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> Dict[str, Any]:
    _require_scope(request, "runs:read")
    if run_id in _get_console_mode_runs(request):
        return await _module_run_detail(run_id, request)
    return await _flow_run_detail(run_id, request)


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> StreamingResponse:
    _require_scope(request, "runs:read")
    detail = await get_run(run_id, request)
    timeline = detail.get("timeline") if isinstance(detail.get("timeline"), list) else []

    async def event_stream() -> AsyncIterator[bytes]:
        yield _sse_event(
            "run.started",
            {
                "run_id": run_id,
                "target_type": detail.get("target_type"),
                "target_id": detail.get("target_id"),
                "started_at": detail.get("created_at"),
            },
        )
        for item in timeline:
            yield _sse_event("node.event", item)
        final_event = "run.completed"
        if detail.get("status") == "failed":
            final_event = "run.failed"
        elif detail.get("status") == "stopped":
            final_event = "run.stopped"
        yield _sse_event(
            final_event,
            {
                "run_id": run_id,
                "status": detail.get("status"),
                "updated_at": detail.get("updated_at"),
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}/artifacts")
async def get_run_artifacts(run_id: str, request: Request) -> Dict[str, Any]:
    _require_scope(request, "runs:read")
    detail = await get_run(run_id, request)
    artifacts = detail.get("artifacts") if isinstance(detail.get("artifacts"), list) else []
    return {"run_id": run_id, "artifacts": artifacts}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request) -> Dict[str, Any]:
    _require_scope(request, "runs:write")
    detail = await get_run(run_id, request)
    if detail.get("status") in {"done", "failed", "stopped"}:
        return {
            "run_id": run_id,
            "status": detail.get("status"),
            "cancelled": False,
            "message": "run already terminal",
        }
    return {
        "run_id": run_id,
        "status": detail.get("status"),
        "cancelled": False,
        "message": "cancel_not_supported_yet",
    }

