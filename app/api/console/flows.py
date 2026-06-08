from __future__ import annotations
import logging

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from app.core.blocks import build_default_registry
from app.core.realtime.sagas.artifact_store import ArtifactStore
from app.core.saga_blueprints import BlueprintStatus
from app.services.saga_architect import SagaArchitect

from app.api.console.utils import (
    FlowCompileRequest,
    ReleaseRequest,
    RunCreateRequest,
    RunTarget,
    _CONTEXT_ROOTS,
    _blueprint_to_flow_graph,
    _canonicalize_blueprint_steps,
    _canonical_sha256,
    _create_flow_run,
    _flow_document,
    _flow_run_detail,
    _get_blueprint_store,
    _graph_to_blueprint_steps,
    _now_iso,
    _require_any_scope,
    _require_scope,
    _validate_flow_contract_blueprint,
    _validate_flow_contract_graph,
    _write_release_record,
    module_registry,
)


logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/flows")
async def list_flows(request: Request) -> Dict[str, Any]:
    _require_scope(request, "flows:read")
    store = _get_blueprint_store(request)
    try:
        records = await store.list_records()
    except Exception:
        records = []
    flows = [_flow_document(record) for record in records]
    flows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return {"flows": flows}


@router.get("/flows/{flow_id}")
async def get_flow(flow_id: str, request: Request) -> Dict[str, Any]:
    _require_scope(request, "flows:read")
    store = _get_blueprint_store(request)
    record = await store.get_record(flow_id)
    if not record:
        raise HTTPException(status_code=404, detail="flow_not_found")
    return _flow_document(record)


@router.post("/flows/compile")
async def compile_flow(payload: FlowCompileRequest, request: Request) -> Dict[str, Any]:
    ctx = _require_any_scope(request, ["flows:write", "flows:*"])

    flow_id = str(payload.flow_id or f"flow_{uuid.uuid4().hex[:10]}").strip()
    version = str(payload.version or "v1").strip() or "v1"

    graph_nodes = payload.graph.get("nodes") if isinstance(payload.graph.get("nodes"), list) else []
    graph_edges = payload.graph.get("edges") if isinstance(payload.graph.get("edges"), list) else []
    blueprint_steps = payload.blueprint.get("steps") if isinstance(payload.blueprint.get("steps"), list) else []

    if blueprint_steps:
        raw_blueprint = {
            "name": flow_id,
            "version": version,
            "steps": blueprint_steps,
            "entrypoint_schema": payload.entrypoint_schema,
            "assertions": payload.assertions,
            "observability": payload.observability,
        }
        if not graph_nodes:
            graph_nodes, graph_edges = _blueprint_to_flow_graph(raw_blueprint)
    else:
        if not graph_nodes:
            raise HTTPException(status_code=400, detail="flow_graph_required")
        blueprint_steps = _graph_to_blueprint_steps(graph_nodes, graph_edges)
        raw_blueprint = {
            "name": flow_id,
            "version": version,
            "steps": blueprint_steps,
            "entrypoint_schema": payload.entrypoint_schema,
            "assertions": payload.assertions,
            "observability": payload.observability,
            "graph": {
                "nodes": graph_nodes,
                "edges": graph_edges,
            },
        }

    contract_validation = _validate_flow_contract_graph(graph_nodes, graph_edges)
    if not contract_validation.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "incompatible_flow_contract",
                "issues": contract_validation.get("issues", []),
                "errors": contract_validation.get("errors", []),
            },
        )
    blueprint_steps = _graph_to_blueprint_steps(graph_nodes, graph_edges)
    raw_blueprint["steps"] = blueprint_steps
    raw_blueprint["contract_validation"] = contract_validation

    compiled_payload = {
        "flow_id": flow_id,
        "version": version,
        "graph": {
            "flow_id": flow_id,
            "version": version,
            "nodes": graph_nodes,
            "edges": graph_edges,
        },
        "compiled_blueprint": raw_blueprint,
        "entrypoint_schema": payload.entrypoint_schema,
        "assertions": payload.assertions,
        "observability": payload.observability,
        "contract_validation": contract_validation,
        "compiled_at": _now_iso(),
        "compiled_by": ctx.user_id,
    }
    artifact_store = ArtifactStore()
    artifact_ref = artifact_store.store(
        saga_id=f"flow:{flow_id}",
        step="compile",
        kind="compiled_mode_payload",
        payload=compiled_payload,
    )
    raw_blueprint["compiled_mode_payload_ref"] = artifact_ref

    status = BlueprintStatus.DRAFT
    store = _get_blueprint_store(request)
    existing = await store.get_record(flow_id)
    if existing:
        status = existing.status
    if payload.save:
        await store.save(flow_id, raw_blueprint, owner_id=ctx.user_id, status=status)

    return {
        "flow_id": flow_id,
        "version": version,
        "compiled_mode_payload_ref": artifact_ref,
        "saved": payload.save,
        "contract_validation": contract_validation,
        "flow": {
            "flow_id": flow_id,
            "version": version,
            "nodes": graph_nodes,
            "edges": graph_edges,
            "entrypoint_schema": payload.entrypoint_schema,
            "assertions": payload.assertions,
            "observability": payload.observability,
            "raw_blueprint": raw_blueprint,
        },
    }


@router.post("/flows/{flow_id}/validate")
async def validate_flow(flow_id: str, request: Request) -> Dict[str, Any]:
    _require_any_scope(request, ["flows:write", "flows:*"])
    store = _get_blueprint_store(request)
    record = await store.get_record(flow_id)
    if not record:
        raise HTTPException(status_code=404, detail="flow_not_found")

    registry = build_default_registry()
    architect = SagaArchitect(registry)
    blueprint = _canonicalize_blueprint_steps(
        record.data if isinstance(record.data, dict) else {}
    )
    validation = architect.validate_blueprint(blueprint)
    _validate_errors = []
    if not validation.get("ok"):
        _validate_errors = [str(err) for err in (validation.get("errors") or [])]
    contract_validation = _validate_flow_contract_blueprint(blueprint)
    contract_errors = [str(error) for error in (contract_validation.get("errors") or [])]

    return {
        "ok": len(_validate_errors) == 0 and len(contract_errors) == 0,
        "checks": {
            "graph_contract": {
                "ok": len(_validate_errors) == 0,
                "errors": _validate_errors,
            },
            "contract_compatibility": contract_validation,
            "assertions": {"status": "not_executed"},
        },
        "errors": [*_validate_errors, *contract_errors],
    }


@router.post("/flows/{flow_id}/sandbox")
async def sandbox_flow(flow_id: str, request: Request) -> Dict[str, Any]:
    """Dry-run a draft flow and mark it as SANDBOXED after a clean stub run."""
    ctx = _require_any_scope(request, ["flows:write", "flows:*"])
    store = _get_blueprint_store(request)
    record = await store.get_record(flow_id)
    if not record:
        raise HTTPException(status_code=404, detail="flow_not_found")
    if record.status not in (BlueprintStatus.DRAFT, BlueprintStatus.SANDBOXED):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_transition",
                "current_status": record.status.value,
                "message": "Only DRAFT or SANDBOXED flows can be sandboxed.",
            },
        )

    registry = build_default_registry()
    architect = SagaArchitect(registry)
    blueprint = _canonicalize_blueprint_steps(
        record.data if isinstance(record.data, dict) else {}
    )
    validation = architect.validate_blueprint(blueprint)
    if not validation.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_flow", "details": validation.get("errors", [])},
        )
    contract_validation = _validate_flow_contract_blueprint(blueprint)
    if not contract_validation.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "incompatible_flow_contract",
                "issues": contract_validation.get("issues", []),
                "errors": contract_validation.get("errors", []),
            },
        )

    dry_run: Dict[str, Any] = {}
    try:
        created = await _create_flow_run(
            RunCreateRequest(
                target=RunTarget(type="flow", id=flow_id),
                mode="stub",
                input={
                    "user_id": "00000000-0000-0000-0000-000000000000",
                    "persona": {"keywords": ["sandbox"], "title": "Sandbox"},
                },
            ),
            request,
            auth_ctx=ctx,
        )
        detail = await _flow_run_detail(str(created.get("run_id")), request)
        result = detail.get("result") if isinstance(detail.get("result"), dict) else {}
        passed = (
            created.get("status") == "done"
            and str(result.get("stop_reason") or "") != "node_failed"
        )
        dry_run = {
            "status": "succeeded" if passed else "failed",
            "execution_mode": "DRY_RUN",
            "run_id": created.get("run_id"),
            "raw_status": created.get("raw_status"),
            "result": result,
            "execution_trace": detail.get("timeline") if isinstance(detail.get("timeline"), list) else [],
        }
        if passed:
            record = await store.update_status(flow_id, BlueprintStatus.SANDBOXED) or record
    except Exception as exc:
        dry_run = {"status": "failed", "error": str(exc)}

    return {
        "name": record.name,
        "status": record.status.value,
        "dry_run": dry_run,
    }


@router.post("/flows/{flow_id}/release")
async def release_flow(
    flow_id: str,
    payload: ReleaseRequest,
    request: Request,
) -> Dict[str, Any]:
    ctx = _require_any_scope(request, ["modules:release", "flows:*", "*"])

    store = _get_blueprint_store(request)
    record = await store.get_record(flow_id)
    if not record:
        raise HTTPException(status_code=404, detail="flow_not_found")

    blueprint = record.data if isinstance(record.data, dict) else {}
    contract_validation = _validate_flow_contract_blueprint(blueprint)
    if not contract_validation.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "incompatible_flow_contract",
                "issues": contract_validation.get("issues", []),
                "errors": contract_validation.get("errors", []),
            },
        )

    try:
        await store.update_status(flow_id, BlueprintStatus.ACTIVE)
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
    release_record = {
        "release_id": str(uuid.uuid4()),
        "target_type": "flow",
        "target_id": flow_id,
        "version": str(payload.version or (record.data or {}).get("version") or "v1"),
        "released_at": _now_iso(),
        "released_by": ctx.user_id,
        "notes": payload.notes,
        "signature": _canonical_sha256(record.data if isinstance(record.data, dict) else {}),
    }
    release_record["artifact_path"] = _write_release_record("flows", flow_id, release_record)
    return release_record

