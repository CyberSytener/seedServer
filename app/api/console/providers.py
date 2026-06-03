from __future__ import annotations
import logging

from typing import Any, Dict


from fastapi import APIRouter, HTTPException, Request

from app.core.authz import audit_auth_event

from app.api.console.utils import (
    ProviderProfileUpsertRequest,
    _CONTEXT_ROOTS,
    _DEFAULT_PROVIDER_PROFILE_ID,
    _delete_provider_profile,
    _provider_profiles,
    _require_any_scope,
    _upsert_provider_profile,
    module_registry,
)


logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/provider-profiles")
async def list_provider_profiles(request: Request) -> Dict[str, Any]:
    _require_any_scope(request, ["providers:read", "runs:write"])
    profiles = []
    for profile in _provider_profiles(request).values():
        if not isinstance(profile, dict):
            continue
        profiles.append(
            {
                "id": str(profile.get("id") or ""),
                "enabled": bool(profile.get("enabled", False)),
                "allowed_models": profile.get("allowed_models") if isinstance(profile.get("allowed_models"), list) else [],
                "daily_budget_units": float(profile.get("daily_budget_units") or 0.0),
                "per_run_cap_units": float(profile.get("per_run_cap_units") or 0.0),
                "requires_scope": str(profile.get("requires_scope") or "providers:use:real"),
                "timeout_caps": profile.get("timeout_caps") if isinstance(profile.get("timeout_caps"), dict) else {},
                "retry_caps": profile.get("retry_caps") if isinstance(profile.get("retry_caps"), dict) else {},
                "redaction_policy": profile.get("redaction_policy") if isinstance(profile.get("redaction_policy"), dict) else {},
            }
        )
    return {"profiles": profiles}


@router.get("/provider-profiles/{profile_id}")
async def get_provider_profile(profile_id: str, request: Request) -> Dict[str, Any]:
    _require_any_scope(request, ["providers:read", "runs:write"])
    profile = _provider_profiles(request).get(profile_id)
    if not isinstance(profile, dict):
        raise HTTPException(status_code=404, detail="provider_profile_not_found")
    return {"profile": profile}


@router.put("/provider-profiles/{profile_id}")
async def upsert_provider_profile(
    profile_id: str,
    payload: ProviderProfileUpsertRequest,
    request: Request,
) -> Dict[str, Any]:
    ctx = _require_any_scope(request, ["providers:write", "*"])
    existing = _provider_profiles(request).get(profile_id)
    merged = dict(existing) if isinstance(existing, dict) else {"id": profile_id}

    if payload.enabled is not None:
        merged["enabled"] = bool(payload.enabled)
    if payload.allowed_models is not None:
        merged["allowed_models"] = [str(item) for item in payload.allowed_models if str(item).strip()]
    if payload.daily_budget_units is not None:
        merged["daily_budget_units"] = max(0.0, float(payload.daily_budget_units))
    if payload.per_run_cap_units is not None:
        merged["per_run_cap_units"] = max(0.0, float(payload.per_run_cap_units))
    if payload.timeout_caps is not None:
        merged["timeout_caps"] = payload.timeout_caps
    if payload.retry_caps is not None:
        merged["retry_caps"] = payload.retry_caps
    if payload.redaction_policy is not None:
        merged["redaction_policy"] = payload.redaction_policy
    if payload.requires_scope is not None:
        merged["requires_scope"] = str(payload.requires_scope).strip() or "providers:use:real"

    operation, profile = _upsert_provider_profile(
        request,
        profile_id=profile_id,
        payload=merged,
        actor_user_id=ctx.user_id,
    )
    audit_auth_event(
        action="provider_profiles.write",
        request=request,
        context=ctx,
        allowed=True,
        details={
            "operation": operation,
            "profile_id": profile_id,
        },
    )
    return {"ok": True, "operation": operation, "profile": profile}


@router.delete("/provider-profiles/{profile_id}")
async def delete_provider_profile(profile_id: str, request: Request) -> Dict[str, Any]:
    ctx = _require_any_scope(request, ["providers:write", "*"])
    if profile_id == _DEFAULT_PROVIDER_PROFILE_ID:
        raise HTTPException(status_code=400, detail="cannot_delete_default_provider_profile")
    existed = _delete_provider_profile(request, profile_id)
    if not existed:
        raise HTTPException(status_code=404, detail="provider_profile_not_found")
    audit_auth_event(
        action="provider_profiles.delete",
        request=request,
        context=ctx,
        allowed=True,
        details={"profile_id": profile_id},
    )
    return {"ok": True, "deleted": True, "profile_id": profile_id}

