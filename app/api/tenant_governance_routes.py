from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.auth import require_admin_key
from app.infrastructure.db.sqlite import DB
from app.services.tenant_governance import METRIC_VALUES, ROLE_VALUES, WINDOW_VALUES, TenantGovernanceService


class GovernanceBaseModel(BaseModel):
    model_config = {"protected_namespaces": ()}


class UpsertTenantRequest(GovernanceBaseModel):
    tenant_id: str
    display_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpsertProjectRequest(GovernanceBaseModel):
    project_id: str
    display_name: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GrantRoleRequest(GovernanceBaseModel):
    user_id: str
    role: str
    project_id: Optional[str] = None


class SetQuotaRequest(GovernanceBaseModel):
    operation: str
    window: str
    limit_value: float
    metric: str = "quantity"
    project_id: Optional[str] = None
    hard_limit: bool = True


class CheckQuotaRequest(GovernanceBaseModel):
    operation: str
    project_id: Optional[str] = None
    quantity: float = 1.0
    cost_usd: float = 0.0
    credits: float = 0.0


class RecordUsageRequest(GovernanceBaseModel):
    operation: str
    project_id: Optional[str] = None
    quantity: float = 1.0
    cost_usd: float = 0.0
    credits: float = 0.0
    enforce_quotas: bool = True
    status: str = "ok"
    error: Optional[str] = None


def build_tenant_governance_router(*, db: DB) -> APIRouter:
    router = APIRouter(tags=["tenant-governance"])
    service = TenantGovernanceService(db)

    def _require_admin(request: Request) -> str:
        ctx = require_admin_key(request)
        return ctx.user_id

    @router.post("/v1/admin/tenants", tags=["admin"])
    async def upsert_tenant(req: UpsertTenantRequest, request: Request):
        actor_id = _require_admin(request)
        try:
            tenant = service.upsert_tenant(
                tenant_id=req.tenant_id,
                display_name=req.display_name,
                metadata=req.metadata,
                actor_id=actor_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"tenant": tenant}

    @router.post("/v1/admin/tenants/{tenant_id}/projects", tags=["admin"])
    async def upsert_project(tenant_id: str, req: UpsertProjectRequest, request: Request):
        actor_id = _require_admin(request)
        try:
            project = service.upsert_project(
                tenant_id=tenant_id,
                project_id=req.project_id,
                display_name=req.display_name,
                metadata=req.metadata,
                actor_id=actor_id,
            )
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail in {"tenant_not_found", "project_not_found"} else 400
            raise HTTPException(status_code=status, detail=detail)
        return {"project": project}

    @router.post("/v1/admin/tenants/{tenant_id}/roles", tags=["admin"])
    async def grant_role(tenant_id: str, req: GrantRoleRequest, request: Request):
        actor_id = _require_admin(request)
        role = str(req.role or "").strip().lower()
        if role not in ROLE_VALUES:
            raise HTTPException(status_code=400, detail=f"unsupported_role:{role}")
        try:
            membership = service.grant_role(
                tenant_id=tenant_id,
                user_id=req.user_id,
                role=role,
                actor_id=actor_id,
                project_id=req.project_id,
            )
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail in {"tenant_not_found", "project_not_found"} else 400
            raise HTTPException(status_code=status, detail=detail)
        return {"membership": membership}

    @router.post("/v1/admin/tenants/{tenant_id}/quotas", tags=["admin"])
    async def set_quota(tenant_id: str, req: SetQuotaRequest, request: Request):
        actor_id = _require_admin(request)
        window = str(req.window or "").strip().lower()
        metric = str(req.metric or "").strip().lower()
        if window not in WINDOW_VALUES:
            raise HTTPException(status_code=400, detail=f"unsupported_window:{window}")
        if metric not in METRIC_VALUES:
            raise HTTPException(status_code=400, detail=f"unsupported_metric:{metric}")
        try:
            quota = service.set_quota(
                tenant_id=tenant_id,
                operation=req.operation,
                window=window,
                limit_value=req.limit_value,
                metric=metric,
                actor_id=actor_id,
                project_id=req.project_id,
                hard_limit=bool(req.hard_limit),
            )
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail in {"tenant_not_found", "project_not_found"} else 400
            raise HTTPException(status_code=status, detail=detail)
        return {"quota": quota}

    @router.post("/v1/admin/tenants/{tenant_id}/usage/check", tags=["admin"])
    async def check_quota(tenant_id: str, req: CheckQuotaRequest, request: Request):
        _require_admin(request)
        try:
            result = service.check_quota(
                tenant_id=tenant_id,
                operation=req.operation,
                project_id=req.project_id,
                quantity=req.quantity,
                cost_usd=req.cost_usd,
                credits=req.credits,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return result

    @router.post("/v1/admin/tenants/{tenant_id}/usage/record", tags=["admin"])
    async def record_usage(tenant_id: str, req: RecordUsageRequest, request: Request):
        actor_id = _require_admin(request)
        try:
            result = service.record_usage(
                tenant_id=tenant_id,
                operation=req.operation,
                actor_id=actor_id,
                project_id=req.project_id,
                quantity=req.quantity,
                cost_usd=req.cost_usd,
                credits=req.credits,
                enforce_quotas=bool(req.enforce_quotas),
                status=req.status,
                error=req.error,
            )
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail in {"tenant_not_found", "project_not_found"} else 400
            raise HTTPException(status_code=status, detail=detail)
        return result

    @router.get("/v1/admin/tenants/{tenant_id}/usage/export", tags=["admin"])
    async def export_usage(
        tenant_id: str,
        request: Request,
        hours: int = 24,
        project_id: Optional[str] = None,
    ):
        _require_admin(request)
        try:
            return service.export_usage(
                tenant_id=tenant_id,
                hours=hours,
                project_id=project_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/v1/admin/tenants/{tenant_id}/audit", tags=["admin"])
    async def get_tenant_audit(
        tenant_id: str,
        request: Request,
        limit: int = 50,
        project_id: Optional[str] = None,
    ):
        _require_admin(request)
        return {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "events": service.get_audit(tenant_id=tenant_id, limit=limit, project_id=project_id),
        }

    @router.get("/v1/admin/tenants/{tenant_id}/governance", tags=["admin"])
    async def get_governance_snapshot(tenant_id: str, request: Request):
        _require_admin(request)
        try:
            return service.governance_snapshot(tenant_id=tenant_id)
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail == "tenant_not_found" else 400
            raise HTTPException(status_code=status, detail=detail)

    return router
