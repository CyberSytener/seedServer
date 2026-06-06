from __future__ import annotations
import logging

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from app.api.console.utils import (
    ModuleValidateRequest,
    ReleaseRequest,
    _CONTEXT_ROOTS,
    _canonical_sha256,
    _module_document,
    _now_iso,
    _require_any_scope,
    _require_scope,
    _write_release_record,
    module_registry,
)


logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/modules")
async def list_modules(request: Request, q: Optional[str] = None, tag: Optional[str] = None) -> Dict[str, Any]:
    _require_scope(request, "modules:read")

    query = str(q or "").strip().lower()
    tag_filter = str(tag or "").strip().lower()
    modules: List[Dict[str, Any]] = []
    for row in module_registry.list_modules():
        spec = module_registry.get_module(str(row.get("mode_id") or ""))
        if not spec:
            continue
        doc = _module_document(spec)
        if query:
            haystack = " ".join(
                [
                    doc.get("module_id") or "",
                    doc.get("title") or "",
                    doc.get("description") or "",
                    " ".join(doc.get("tags") or []),
                ]
            ).lower()
            if query not in haystack:
                continue
        if tag_filter:
            tags = [str(item).lower() for item in (doc.get("tags") or [])]
            if tag_filter not in tags:
                continue
        modules.append(doc)

    modules.sort(key=lambda item: item.get("module_id") or "")
    return {"modules": modules}


@router.get("/modules/{module_id}")
async def get_module(module_id: str, request: Request) -> Dict[str, Any]:
    _require_scope(request, "modules:read")

    spec = module_registry.get_module(module_id)
    if not spec:
        raise HTTPException(status_code=404, detail="module_not_found")
    doc = _module_document(spec)
    doc["source_path"] = spec.get("_path")
    return doc


@router.post("/modules/{module_id}/validate")
async def validate_module(module_id: str, payload: ModuleValidateRequest, request: Request) -> Dict[str, Any]:
    _require_any_scope(request, ["modules:write", "modules:read"])

    spec = module_registry.get_module(module_id)
    if not spec:
        raise HTTPException(status_code=404, detail="module_not_found")

    input_schema_ok = isinstance(spec.get("input_schema"), dict)
    output_schema_ok = isinstance(spec.get("output_schema"), dict)
    schema_errors = []
    if not input_schema_ok:
        schema_errors.append("input_schema must be an object")
    if not output_schema_ok:
        schema_errors.append("output_schema must be an object")

    runtime_errors = module_registry.validate_run_request(
        spec=spec,
        control={"requested_capabilities": payload.requested_capabilities},
        data=payload.sample_input,
        policy={"tool_security": spec.get("tool_security") if isinstance(spec.get("tool_security"), dict) else {}},
        include_contract=False,
    )

    contract_issues = module_registry.validate_contract(spec)
    contract_errors = [issue.as_message() for issue in contract_issues]

    all_errors = [*schema_errors, *runtime_errors, *contract_errors]
    return {
        "ok": len(all_errors) == 0,
        "checks": {
            "schema": {"ok": len(schema_errors) == 0, "errors": schema_errors},
            "runtime": {"ok": len(runtime_errors) == 0, "errors": runtime_errors},
            "contract": {
                "ok": len(contract_errors) == 0,
                "errors": contract_errors,
                "issues": [issue.model_dump() for issue in contract_issues],
            },
            "golden": {"status": "not_executed"},
            "cost_regression": {"status": "not_executed"},
        },
        "errors": all_errors,
    }


@router.post("/modules/{module_id}/release")
async def release_module(
    module_id: str,
    payload: ReleaseRequest,
    request: Request,
) -> Dict[str, Any]:
    ctx = _require_any_scope(request, ["modules:release", "*"])

    spec = module_registry.get_module(module_id)
    if not spec:
        raise HTTPException(status_code=404, detail="module_not_found")

    release_record = {
        "release_id": str(uuid.uuid4()),
        "target_type": "module",
        "target_id": module_id,
        "version": str(payload.version or spec.get("module_version") or "v1"),
        "released_at": _now_iso(),
        "released_by": ctx.user_id,
        "notes": payload.notes,
        "signature": _canonical_sha256(spec),
    }
    release_record["artifact_path"] = _write_release_record("modules", module_id, release_record)
    return release_record

