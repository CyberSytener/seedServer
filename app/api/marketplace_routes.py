from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.auth import authenticate, require_admin_key
from app.infrastructure.db.sqlite import DB
from app.services.marketplace import MarketplaceService, VISIBILITY_VALUES
from app.services.module_registry import ModuleRegistry


class MarketplaceBaseModel(BaseModel):
    model_config = {"protected_namespaces": ()}


class UpsertMarketplaceModuleRequest(MarketplaceBaseModel):
    mode_id: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    owner_tenant_id: Optional[str] = None
    visibility: str = "private"
    status: str = "active"
    sandbox_policy: Dict[str, Any] = Field(default_factory=dict)
    billing_policy: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UpdateSandboxPolicyRequest(MarketplaceBaseModel):
    allowed_capabilities: List[str] = Field(default_factory=list)
    blocked_capabilities: List[str] = Field(default_factory=list)
    min_reputation_score: float = 0.0


class UpdateBillingPolicyRequest(MarketplaceBaseModel):
    revenue_share_creator_pct: float = 0.7
    settlement_window_days: int = 30
    minimum_payout_credits: float = 100.0
    monetization_enabled: bool = True
    currency: str = "credits"


class RateModuleRequest(MarketplaceBaseModel):
    rating: int
    review: Optional[str] = None


class RunSettlementRequest(MarketplaceBaseModel):
    run_id: str
    mode_id: Optional[str] = None


def build_marketplace_router(*, db: DB, registry: Optional[ModuleRegistry] = None) -> APIRouter:
    router = APIRouter(tags=["marketplace"])
    service = MarketplaceService(db)
    module_registry = registry or ModuleRegistry()

    def _require_admin(request: Request) -> str:
        ctx = require_admin_key(request)
        return ctx.user_id

    @router.get("/v1/marketplace/modules")
    async def list_marketplace_modules(
        request: Request,
        visibility: Optional[str] = None,
        include_private: bool = False,
    ):
        include_admin_data = False
        if include_private:
            _require_admin(request)
            include_admin_data = True

        normalized_visibility = str(visibility or "").strip().lower()
        if normalized_visibility and normalized_visibility not in VISIBILITY_VALUES:
            raise HTTPException(status_code=400, detail=f"unsupported_visibility:{normalized_visibility}")

        try:
            modules = service.list_listings(
                visibility=normalized_visibility or None,
                include_private=include_private and include_admin_data,
                include_inactive=include_private and include_admin_data,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return {"modules": modules}

    @router.get("/v1/marketplace/modules/{mode_id}")
    async def get_marketplace_module(mode_id: str, request: Request):
        listing = service.get_listing(mode_id=mode_id, include_private=True)
        if listing is None:
            raise HTTPException(status_code=404, detail="mode_not_found")
        if listing["visibility"] != "public":
            _require_admin(request)
        return {"module": listing}

    @router.get("/v1/marketplace/modules/{mode_id}/reputation")
    async def get_marketplace_reputation(mode_id: str):
        listing = service.get_listing(mode_id=mode_id, include_private=True)
        if listing is None:
            raise HTTPException(status_code=404, detail="mode_not_found")
        return {"mode_id": mode_id, "reputation": service.get_reputation(mode_id)}

    @router.post("/v1/marketplace/modules/{mode_id}/ratings")
    async def rate_marketplace_module(mode_id: str, req: RateModuleRequest, request: Request):
        ctx = authenticate(request, db)
        try:
            reputation = service.upsert_rating(
                mode_id=mode_id,
                user_id=ctx.user_id,
                rating=req.rating,
                review=req.review,
            )
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail == "mode_not_found" else 400
            raise HTTPException(status_code=status, detail=detail)
        return {"mode_id": mode_id, "reputation": reputation}

    @router.post("/v1/admin/marketplace/modules", tags=["admin"])
    async def upsert_marketplace_module(req: UpsertMarketplaceModuleRequest, request: Request):
        _require_admin(request)
        if module_registry.get_module(req.mode_id) is None:
            raise HTTPException(status_code=404, detail="mode_not_found")
        try:
            listing = service.upsert_listing(
                mode_id=req.mode_id,
                display_name=req.display_name,
                description=req.description,
                owner_tenant_id=req.owner_tenant_id,
                visibility=req.visibility,
                status=req.status,
                sandbox_policy=req.sandbox_policy,
                billing_policy=req.billing_policy,
                metadata=req.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"module": listing}

    @router.post("/v1/admin/marketplace/modules/{mode_id}/sandbox-policy", tags=["admin"])
    async def update_marketplace_sandbox_policy(mode_id: str, req: UpdateSandboxPolicyRequest, request: Request):
        _require_admin(request)
        try:
            listing = service.update_sandbox_policy(
                mode_id=mode_id,
                sandbox_policy=req.model_dump(),
            )
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail == "mode_not_found" else 400
            raise HTTPException(status_code=status, detail=detail)
        return {"module": listing}

    @router.post("/v1/admin/marketplace/modules/{mode_id}/billing-policy", tags=["admin"])
    async def update_marketplace_billing_policy(mode_id: str, req: UpdateBillingPolicyRequest, request: Request):
        _require_admin(request)
        try:
            listing = service.update_billing_policy(
                mode_id=mode_id,
                billing_policy=req.model_dump(),
            )
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail == "mode_not_found" else 400
            raise HTTPException(status_code=status, detail=detail)
        return {"module": listing}

    @router.get("/v1/admin/marketplace/modules/{mode_id}/usage/export", tags=["admin"])
    async def export_marketplace_usage(mode_id: str, request: Request, hours: int = 24):
        _require_admin(request)
        try:
            payload = service.export_usage(mode_id=mode_id, hours=hours)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return payload

    @router.post("/v1/admin/marketplace/settlements/run", tags=["admin"])
    async def run_marketplace_settlement(req: RunSettlementRequest, request: Request):
        _require_admin(request)
        try:
            result = service.run_settlement(
                run_id=req.run_id,
                mode_id=req.mode_id,
            )
        except ValueError as exc:
            detail = str(exc)
            status = 404 if detail == "mode_not_found" else 400
            raise HTTPException(status_code=status, detail=detail)
        return result

    @router.get("/v1/admin/marketplace/payouts", tags=["admin"])
    async def list_marketplace_payouts(
        request: Request,
        mode_id: Optional[str] = None,
        owner_tenant_id: Optional[str] = None,
        limit: int = 50,
    ):
        _require_admin(request)
        try:
            payouts = service.list_payouts(
                mode_id=mode_id,
                owner_tenant_id=owner_tenant_id,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"payouts": payouts}

    @router.get("/v1/admin/marketplace/payouts/{payout_id}", tags=["admin"])
    async def get_marketplace_payout(payout_id: str, request: Request):
        _require_admin(request)
        payout = service.get_payout(payout_id=payout_id)
        if payout is None:
            raise HTTPException(status_code=404, detail="payout_not_found")
        return {"payout": payout}

    return router
