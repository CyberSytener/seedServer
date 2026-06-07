from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.authz import require_scope
from app.dependencies import get_db
from app.infrastructure.db.sqlite import DB
from app.services.marketplace import MarketplaceService
from app.services.module_registry import ModuleRegistry


router = APIRouter(prefix="/v1/modes", tags=["modes"])
registry = ModuleRegistry()


def _build_marketplace_service(db: Any) -> Optional[MarketplaceService]:
    required_methods = ("execute", "fetchone", "fetchall")
    if not all(hasattr(db, method) for method in required_methods):
        return None
    try:
        return MarketplaceService(db)
    except Exception:
        return None


class ModeSummary(BaseModel):
    mode_id: str
    pipeline: str
    task_type: str
    capabilities: List[str] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class ModesListResponse(BaseModel):
    modes: List[ModeSummary] = Field(default_factory=list)


class RunControl(BaseModel):
    mode: Optional[str] = None
    requested_capabilities: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None


class RunModeRequest(BaseModel):
    control: RunControl = Field(default_factory=RunControl)
    data: Dict[str, Any] = Field(default_factory=dict)


class RunModeResponse(BaseModel):
    mode_id: str
    saga_id: str
    saga_type: str
    task_type: str
    status: str


@router.get("", response_model=ModesListResponse)
async def list_modes() -> ModesListResponse:
    rows = [
        row
        for row in registry.list_modules(pipeline="llm_pipeline")
        if row.get("contract_valid") and row.get("directly_runnable")
    ]
    return ModesListResponse(
        modes=[
            ModeSummary(
                mode_id=row["mode_id"],
                pipeline=row["pipeline"],
                task_type=row["task_type"],
                capabilities=row.get("capabilities") or [],
                output_schema=row.get("output_schema") or {},
            )
            for row in rows
        ]
    )


@router.post("/{mode_id}/run", response_model=RunModeResponse)
async def run_mode(mode_id: str, req: RunModeRequest, request: Request, db: DB = Depends(get_db)) -> RunModeResponse:
    ctx = require_scope(request, db, "runs:write")
    marketplace = _build_marketplace_service(db)

    spec = registry.get_module(mode_id)
    if not spec:
        raise HTTPException(status_code=404, detail="mode_not_found")

    if not registry.is_directly_runnable(spec):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "module_not_directly_runnable",
                "pipeline": str(spec.get("pipeline") or ""),
                "execution_adapter": registry.execution_adapter(spec),
            },
        )

    orchestrator = getattr(request.app.state, "saga_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="saga_orchestrator_unavailable")

    control = req.control.model_dump() if hasattr(req.control, "model_dump") else dict(req.control)

    idempotency_key = str(control.get("idempotency_key") or request.headers.get("Idempotency-Key") or "").strip()
    payload_hash = hashlib.sha256(
        json.dumps({"mode_id": mode_id, "control": control, "data": req.data}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    cache = getattr(request.app.state, "mode_run_idempotency", None)
    if cache is None:
        cache = {}
        request.app.state.mode_run_idempotency = cache
    cache_key = f"{ctx.user_id}:{mode_id}:{idempotency_key}" if idempotency_key else None
    if cache_key and cache_key in cache:
        cached = cache[cache_key]
        if cached.get("payload_hash") != payload_hash:
            raise HTTPException(status_code=409, detail="idempotency key already used with different payload")
        return RunModeResponse(**cached["response"])

    errors = registry.validate_run_request(
        spec=spec,
        control=control,
        data=req.data,
        policy={"tool_security": spec.get("tool_security") if isinstance(spec.get("tool_security"), dict) else {}},
    )

    if marketplace is not None:
        errors.extend(
            marketplace.validate_sandbox_request(
                mode_id=mode_id,
                requested_capabilities=control.get("requested_capabilities") or [],
            )
        )
    if errors:
        raise HTTPException(status_code=400, detail={"error": "invalid_mode_request", "violations": errors})

    payload = registry.build_saga_payload(mode_id=mode_id, spec=spec, control=control, data=req.data)
    marketplace_context = marketplace.runtime_context(mode_id=mode_id) if marketplace is not None else None
    if isinstance(marketplace_context, dict):
        payload["marketplace"] = marketplace_context
    saga_user_id = ctx.user_id

    action_id = str(control.get("idempotency_key") or "").strip() or f"mode:{mode_id}:{ctx.user_id}"
    saga_id = await orchestrator.start_saga(
        action_id=action_id,
        saga_type="llm_pipeline",
        payload=payload,
        user_id=saga_user_id,
    )

    if marketplace is not None and isinstance(marketplace_context, dict):
        try:
            marketplace.record_usage_event(
                mode_id=mode_id,
                consumer_user_id=saga_user_id,
                event_type="run_started",
                credits=0.0,
                cost_usd=0.0,
                metadata={
                    "saga_id": saga_id,
                    "task_type": payload.get("task_type"),
                    "requested_capabilities": control.get("requested_capabilities") or [],
                },
            )
        except Exception:
            # Runtime invocation should not fail if marketplace metering is unavailable.
            pass

    response = RunModeResponse(
        mode_id=mode_id,
        saga_id=saga_id,
        saga_type="llm_pipeline",
        task_type=str(payload.get("task_type") or mode_id),
        status="started",
    )
    if cache_key:
        cache[cache_key] = {
            "payload_hash": payload_hash,
            "response": response.model_dump(),
        }
    return response
