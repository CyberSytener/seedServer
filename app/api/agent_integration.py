from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.saga_blueprints import _get_saga_db_from_request, _run_saga
from app.core.authz import UnifiedAuthContext, require_any_scope, require_scope
from app.core.blocks import build_default_registry
from app.core.realtime.sagas.flows.dynamic_saga import ExecutionMode
from app.core.saga_blueprints import BlueprintStatus, blueprint_store as default_blueprint_store
from app.services.blueprint_normalizer import normalize_blueprint
from app.services.catalog_service import CatalogError, CatalogService
from app.services.saga_architect import SagaArchitect


router = APIRouter(prefix="/v1", tags=["Agent Integration"])
catalog_service = CatalogService()


class AgentBaseModel(BaseModel):
    model_config = {"protected_namespaces": ()}


class GenerateBlueprintRequest(AgentBaseModel):
    prompt: str
    domain: Optional[str] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)
    model_tier: Optional[str] = None
    strict: bool = False
    max_repairs: int = Field(default=1, ge=0, le=1)


class ValidateBlueprintRequest(AgentBaseModel):
    blueprint: Dict[str, Any]
    normalize: bool = False


class DryRunBlueprintRequest(AgentBaseModel):
    blueprint: Dict[str, Any]
    sample_input: Dict[str, Any] = Field(default_factory=dict)
    mode: Literal["DRY_RUN", "STUB"] = "DRY_RUN"
    limits: Dict[str, Any] = Field(default_factory=dict)


class PublishPolicy(AgentBaseModel):
    target_status: Literal["DRAFT", "SANDBOXED", "ACTIVE"] = "DRAFT"
    require_admin_approval: bool = True


class PublishBlueprintRequest(AgentBaseModel):
    name: str
    version: Optional[str] = None
    blueprint: Dict[str, Any]
    policy: PublishPolicy = Field(default_factory=PublishPolicy)


class ContextPackRequest(AgentBaseModel):
    domain: Optional[str] = None
    intent: Optional[str] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)
    max_modules: int = Field(default=12, ge=1, le=50)
    include_manifests: bool = False


def _runtime_db(request: Request) -> Any:
    seed_state = getattr(request.app.state, "seed", None)
    return getattr(seed_state, "db", None)


def _require_bearer_token_for_agent_api(request: Request) -> str:
    raw = str(request.headers.get("Authorization") or "").strip()
    if not raw or not raw.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "missing_authorization",
                "message": "Authorization: Bearer <token> is required.",
            },
        )
    token = raw.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_authorization",
                "message": "Authorization bearer token is empty.",
            },
        )
    return token


def _require_scope_ctx(request: Request, scope: str) -> UnifiedAuthContext:
    db = _runtime_db(request)
    if db is None:
        raise HTTPException(status_code=503, detail="auth_backend_unavailable")
    return require_scope(request, db, scope)


def _require_any_scope_ctx(request: Request, scopes: list[str]) -> UnifiedAuthContext:
    db = _runtime_db(request)
    if db is None:
        raise HTTPException(status_code=503, detail="auth_backend_unavailable")
    return require_any_scope(request, db, scopes)


def _require_user_scope_ctx(request: Request, scope: str) -> UnifiedAuthContext:
    _require_bearer_token_for_agent_api(request)
    return _require_scope_ctx(request, scope)


def _effective_user_id(ctx: UnifiedAuthContext) -> Optional[str]:
    candidate = str(getattr(ctx, "user_id", "") or "").strip()
    if not candidate or candidate.lower() in {"unknown", "anonymous", "none"}:
        return None
    return candidate


def _get_blueprint_store(request: Request) -> Any:
    return getattr(request.app.state, "agent_blueprint_store", default_blueprint_store)


def _validate_blueprint_or_400(architect: SagaArchitect, blueprint: Dict[str, Any]) -> Dict[str, Any]:
    allowed_blocks = []
    registry = getattr(architect, "_registry", None)
    if registry is not None and callable(getattr(registry, "list_blocks", None)):
        allowed_blocks = list(registry.list_blocks())
    result = architect.validate_blueprint(blueprint)
    normalized_errors = _normalize_validation_errors(result.get("errors") or [], allowed_blocks)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_blueprint",
                "message": "Blueprint validation failed.",
                "details": normalized_errors,
            },
        )
    result["errors"] = normalized_errors
    return result


def _observability_usage(meta: Dict[str, Any]) -> Dict[str, Optional[int]]:
    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _normalize_validation_errors(errors: List[Any], allowed_blocks: List[str]) -> List[Any]:
    normalized: List[Any] = []
    pattern = re.compile(r"^step\[\d+\]\s+\((?P<step_id>.+?)\)\s+unknown block type:\s*(?P<block>.+)$")
    for item in errors:
        if isinstance(item, dict):
            if item.get("error") == "unknown_block" and "allowed_blocks" not in item:
                copy = dict(item)
                copy["allowed_blocks"] = allowed_blocks[:64]
                normalized.append(copy)
            else:
                normalized.append(item)
            continue
        text = str(item)
        matched = pattern.match(text)
        if matched:
            normalized.append(
                {
                    "error": "unknown_block",
                    "step_id": matched.group("step_id"),
                    "block": matched.group("block"),
                    "allowed_blocks": allowed_blocks[:64],
                }
            )
            continue
        normalized.append(text)
    return normalized


def _build_blueprint_fix_prompt(
    *,
    previous_blueprint: Dict[str, Any],
    errors: List[Any],
    allowed_blocks: List[str],
) -> str:
    dsl_summary = (
        "DSL v0: Return a single JSON object with keys name(string), version(string), steps(array). "
        "Each step must include id(string), block(string), inputs(object). "
        "Input references must use {\"from\": \"...\"} mapping form."
    )
    error_payload: List[Any] = []
    for item in errors or []:
        if isinstance(item, dict):
            error_payload.append(item)
        else:
            error_payload.append({"error": "validation_error", "message": str(item)})
    error_payload = error_payload[:12]
    block_preview = ", ".join(allowed_blocks[:32])
    return (
        "Fix the blueprint to satisfy validation.\n"
        "Return ONLY valid blueprint JSON, no markdown and no prose.\n\n"
        f"{dsl_summary}\n"
        f"Allowed blocks: {block_preview}\n"
        f"Validation errors: {json.dumps(error_payload, ensure_ascii=True)}\n"
        f"Previous blueprint JSON: {json.dumps(previous_blueprint, ensure_ascii=True)}"
    )


def _build_context_pack_response(
    *,
    domain: Optional[str],
    intent: Optional[str],
    constraints: Dict[str, Any],
    max_modules: int,
    include_manifests: bool,
) -> Dict[str, Any]:
    return catalog_service.build_context_pack(
        domain=domain,
        intent=intent,
        constraints=constraints,
        max_modules=max_modules,
        include_manifests=include_manifests,
    )


@router.get("/catalog/tree")
async def get_catalog_tree(request: Request) -> Dict[str, Any]:
    _require_user_scope_ctx(request, "catalog:read")
    return catalog_service.load_tree()


@router.get("/catalog/node/{path:path}")
async def get_catalog_node(path: str, request: Request) -> Dict[str, Any]:
    _require_user_scope_ctx(request, "catalog:read")
    try:
        return catalog_service.load_node(path)
    except CatalogError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_catalog_path", "message": str(exc)},
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": "catalog_node_not_found", "message": str(exc)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": "catalog_node_invalid_json", "message": str(exc)},
        ) from exc


@router.get("/catalog/search")
async def search_catalog(
    request: Request,
    q: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    _require_user_scope_ctx(request, "catalog:read")
    return {
        "query": q,
        "tag": tag,
        "results": catalog_service.search(q=q, tag=tag),
    }


@router.get("/catalog/context-pack")
async def get_catalog_context_pack(
    request: Request,
    domain: Optional[str] = Query(default=None),
    intent: Optional[str] = Query(default=None),
    constraints: Optional[str] = Query(default=None, description="JSON encoded constraints object."),
    max_modules: int = Query(default=12, ge=1, le=50),
    include_manifests: bool = Query(default=False),
) -> Dict[str, Any]:
    _require_user_scope_ctx(request, "catalog:read")
    constraints_payload: Dict[str, Any] = {}
    if constraints:
        try:
            parsed = json.loads(constraints)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_constraints_json", "message": str(exc)},
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_constraints_shape",
                    "message": "constraints must decode to a JSON object.",
                },
            )
        constraints_payload = parsed

    return _build_context_pack_response(
        domain=domain,
        intent=intent,
        constraints=constraints_payload,
        max_modules=max_modules,
        include_manifests=include_manifests,
    )


@router.post("/catalog/context-pack")
async def post_catalog_context_pack(request: Request, payload: ContextPackRequest) -> Dict[str, Any]:
    _require_user_scope_ctx(request, "catalog:read")
    return _build_context_pack_response(
        domain=payload.domain,
        intent=payload.intent,
        constraints=payload.constraints,
        max_modules=payload.max_modules,
        include_manifests=payload.include_manifests,
    )


@router.post("/blueprints/generate")
async def generate_blueprint(request: Request, payload: GenerateBlueprintRequest) -> Dict[str, Any]:
    _require_user_scope_ctx(request, "blueprints:write")
    registry = build_default_registry()
    architect = SagaArchitect(registry)
    started_at = time.perf_counter()

    prompt = payload.prompt.strip()
    if payload.constraints:
        prompt = f"{prompt}\n\nConstraints(JSON): {json.dumps(payload.constraints, ensure_ascii=True, sort_keys=True)}"

    raw_blueprint, model_meta = await architect.draft_blueprint(
        prompt,
        model_tier=payload.model_tier,
        domain=payload.domain,
    )
    normalized_blueprint, fixes_applied = normalize_blueprint(raw_blueprint, registry=registry)
    validation_raw = architect.validate_blueprint(normalized_blueprint)
    validation = {
        "ok": bool(validation_raw.get("ok")),
        "errors": _normalize_validation_errors(
            list(validation_raw.get("errors") or []),
            registry.list_blocks(),
        ),
    }

    reprompted = False
    final_raw_blueprint: Any = raw_blueprint
    final_normalized_blueprint = normalized_blueprint
    final_validation = validation
    final_model_meta = model_meta
    final_fixes_applied = fixes_applied

    if (not validation.get("ok")) and payload.strict and payload.max_repairs > 0:
        reprompted = True
        fix_prompt = _build_blueprint_fix_prompt(
            previous_blueprint=normalized_blueprint,
            errors=list(validation.get("errors") or []),
            allowed_blocks=registry.list_blocks(),
        )
        repair_raw_blueprint, repair_model_meta = await architect.draft_blueprint(
            fix_prompt,
            model_tier=payload.model_tier,
            domain=payload.domain,
        )
        repair_normalized_blueprint, repair_fixes_applied = normalize_blueprint(repair_raw_blueprint, registry=registry)
        repair_validation_raw = architect.validate_blueprint(repair_normalized_blueprint)
        repair_validation = {
            "ok": bool(repair_validation_raw.get("ok")),
            "errors": _normalize_validation_errors(
                list(repair_validation_raw.get("errors") or []),
                registry.list_blocks(),
            ),
        }

        first_errors = len(validation.get("errors") or [])
        second_errors = len(repair_validation.get("errors") or [])
        if repair_validation.get("ok") or second_errors <= first_errors:
            final_raw_blueprint = repair_raw_blueprint
            final_normalized_blueprint = repair_normalized_blueprint
            final_validation = repair_validation
            final_model_meta = repair_model_meta
            final_fixes_applied = repair_fixes_applied

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    usage_payload = _observability_usage(final_model_meta if isinstance(final_model_meta, dict) else {})
    return {
        "ok": bool(final_validation.get("ok")),
        "final_ok": bool(final_validation.get("ok")),
        "blueprint": final_raw_blueprint,
        "raw_blueprint": final_raw_blueprint,
        "normalized_blueprint": final_normalized_blueprint,
        "fixes_applied": final_fixes_applied,
        "validation": final_validation,
        "reprompted": reprompted,
        "repair_attempts": 1 if reprompted else 0,
        "model": final_model_meta,
        "effective_model_tier": final_model_meta.get("model_tier") if isinstance(final_model_meta, dict) else None,
        "effective_model_name": final_model_meta.get("model_name") if isinstance(final_model_meta, dict) else None,
        "elapsed_ms": elapsed_ms,
        "provider_request_id": (
            final_model_meta.get("provider_request_id") if isinstance(final_model_meta, dict) else None
        ),
        "usage": usage_payload,
        "cost": final_model_meta.get("cost") if isinstance(final_model_meta, dict) else None,
    }


@router.post("/blueprints/validate")
async def validate_blueprint(request: Request, payload: ValidateBlueprintRequest) -> Dict[str, Any]:
    _require_user_scope_ctx(request, "blueprints:write")
    registry = build_default_registry()
    architect = SagaArchitect(registry)
    target_blueprint = payload.blueprint
    normalized_blueprint: Optional[Dict[str, Any]] = None
    fixes_applied: List[str] = []
    if payload.normalize:
        normalized_blueprint, fixes_applied = normalize_blueprint(payload.blueprint, registry=registry)
        target_blueprint = normalized_blueprint
    validation_raw = architect.validate_blueprint(target_blueprint)
    validation = {
        "ok": bool(validation_raw.get("ok")),
        "errors": _normalize_validation_errors(
            list(validation_raw.get("errors") or []),
            registry.list_blocks(),
        ),
    }
    response: Dict[str, Any] = {
        "ok": bool(validation["ok"]),
        "errors": list(validation.get("errors") or []),
        "warnings": [],
    }
    if payload.normalize:
        response["normalized_blueprint"] = normalized_blueprint or {}
        response["fixes_applied"] = fixes_applied
    return response


@router.post("/blueprints/dry-run")
async def dry_run_blueprint(request: Request, payload: DryRunBlueprintRequest) -> Dict[str, Any]:
    ctx = _require_user_scope_ctx(request, "blueprints:write")
    _require_user_scope_ctx(request, "runs:write")
    architect = SagaArchitect(build_default_registry())
    _validate_blueprint_or_400(architect, payload.blueprint)

    max_steps_raw = payload.limits.get("max_steps", 25)
    timeout_raw = payload.limits.get("timeout_sec", 20)
    try:
        max_steps = max(1, min(int(max_steps_raw), 100))
    except Exception:
        max_steps = 25
    try:
        timeout_sec = max(1.0, min(float(timeout_raw), 60.0))
    except Exception:
        timeout_sec = 20.0

    blueprint_copy = dict(payload.blueprint)
    steps = blueprint_copy.get("steps") if isinstance(blueprint_copy.get("steps"), list) else []
    warnings: list[str] = []
    if len(steps) > max_steps:
        blueprint_copy["steps"] = steps[:max_steps]
        warnings.append(f"step_limit_applied:{max_steps}")

    sample_input = dict(payload.sample_input)
    user_id = _effective_user_id(ctx) or "anonymous"
    if "user_id" not in sample_input and not (
        isinstance(sample_input.get("request"), dict) and sample_input["request"].get("user_id")
    ):
        sample_input["user_id"] = user_id

    try:
        result = await asyncio.wait_for(
            _run_saga(
                blueprint_copy,
                sample_input,
                build_default_registry(),
                execution_mode=ExecutionMode.DRY_RUN,
                db=_get_saga_db_from_request(request),
                actor_user_id=user_id,
            ),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=408,
            detail={
                "error": "dry_run_timeout",
                "message": f"Dry-run exceeded timeout ({timeout_sec:.1f}s).",
            },
        ) from None

    trace = result.get("execution_trace", []) if isinstance(result, dict) else []
    return {
        "ok": True,
        "mode": payload.mode,
        "runtime_execution_mode": "DRY_RUN",
        "status": result.get("status", "unknown") if isinstance(result, dict) else "unknown",
        "execution_trace": trace if isinstance(trace, list) else [],
        "failed_step_id": result.get("failed_step_id") if isinstance(result, dict) else None,
        "failed_block": result.get("failed_block") if isinstance(result, dict) else None,
        "warnings": warnings,
    }


@router.post("/blueprints/publish")
async def publish_blueprint(request: Request, payload: PublishBlueprintRequest) -> Dict[str, Any]:
    ctx = _require_user_scope_ctx(request, "blueprints:write")
    architect = SagaArchitect(build_default_registry())
    _validate_blueprint_or_400(architect, payload.blueprint)

    blueprint_name = payload.name.strip()
    if not blueprint_name:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_name", "message": "Blueprint name is required."},
        )

    desired = payload.policy.target_status
    status = BlueprintStatus.DRAFT
    approval_required = False

    if desired == "SANDBOXED":
        status = BlueprintStatus.SANDBOXED

    if desired == "ACTIVE":
        if payload.policy.require_admin_approval:
            status = BlueprintStatus.SANDBOXED
            approval_required = True
        else:
            publish_ctx = _require_user_scope_ctx(request, "blueprints:publish")
            if not publish_ctx.is_admin:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "admin_required",
                        "message": "Admin role is required for direct ACTIVE publish.",
                    },
                )
            status = BlueprintStatus.ACTIVE

    blueprint_data = dict(payload.blueprint)
    blueprint_data["name"] = blueprint_name
    if payload.version:
        blueprint_data["version"] = payload.version

    store = _get_blueprint_store(request)
    record = await store.save(
        blueprint_name,
        blueprint_data,
        owner_id=ctx.user_id,
        status=status,
    )

    return {
        "ok": True,
        "name": record.name,
        "owner_id": record.owner_id,
        "version": str(blueprint_data.get("version") or "v1"),
        "status": record.status.value,
        "desired_status": desired,
        "approval_required": approval_required,
    }
