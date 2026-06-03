from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from app.core.auth import authenticate, require_admin_key
from app.infrastructure.db.sqlite import DB
from app.models.api import DiagnosticGenerateRequest


def build_admin_router(
    *,
    db: DB,
    set_system_mode: Callable[[str], Awaitable[None]],
) -> APIRouter:
    router = APIRouter()

    def _require_admin(request: Request):
        return require_admin_key(request)

    @router.post("/v1/admin/mode")
    async def admin_set_mode(request: Request):
        _require_admin(request)
        body = await request.json()
        mode = str(body.get("mode") or "")
        await set_system_mode(mode)
        return {"mode": mode}

    @router.get("/v1/feature-flags", tags=["admin"])
    async def list_feature_flags(request: Request):
        from app.core.feature_flags import FeatureFlagManager

        _require_admin(request)

        manager = FeatureFlagManager(db)
        flags = manager.get_all_flags()
        return {
            "flags": [
                {
                    "name": flag.name,
                    "enabled": flag.enabled,
                    "strategy": flag.strategy.value,
                    "config": flag.config,
                    "description": flag.description,
                }
                for flag in flags.values()
            ]
        }

    @router.post("/v1/feature-flags/{flag_name}/toggle", tags=["admin"])
    async def toggle_feature_flag(flag_name: str, request: Request, enabled: bool):
        from app.core.feature_flags import FeatureFlagManager

        ctx = _require_admin(request)

        manager = FeatureFlagManager(db)
        try:
            manager.update_flag(flag_name, enabled=enabled)
            logging.info(
                f"Feature flag '{flag_name}' {'enabled' if enabled else 'disabled'} by {ctx.user_id}"
            )
            return {"status": "success", "flag": flag_name, "enabled": enabled}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.post("/v1/ab-tests/run", tags=["admin"])
    async def run_ab_test(request: Request):
        from app.core.ab_testing import ABTestRunner, create_standard_test_blueprint

        _require_admin(request)

        variant_a = {"name": "baseline", "optimize_mode": False}
        variant_b = {"name": "optimized_v2", "optimize_mode": True}

        blueprint = create_standard_test_blueprint()
        test_request = DiagnosticGenerateRequest(
            native_lang="Russian",
            target_lang="English",
            blueprint=blueprint,
        )

        runner = ABTestRunner(db)
        test_id = f"auto_test_{int(time.time())}"

        try:
            result = runner.run_single_test(
                test_id=test_id,
                variant_a_config=variant_a,
                variant_b_config=variant_b,
                test_request=test_request,
            )
            return {
                "test_id": result.test_id,
                "winner": result.winner,
                "improvements": {
                    "duration_pct": round(result.duration_improvement_pct, 2),
                    "token_reduction_pct": round(result.token_reduction_pct, 2),
                },
                "variant_a": {
                    "name": result.variant_a,
                    "duration_ms": round(result.a_duration_ms, 2),
                    "tokens": result.a_token_count,
                    "items": result.a_item_count,
                    "success": result.a_success,
                },
                "variant_b": {
                    "name": result.variant_b,
                    "duration_ms": round(result.b_duration_ms, 2),
                    "tokens": result.b_token_count,
                    "items": result.b_item_count,
                    "success": result.b_success,
                },
            }
        except Exception as exc:
            logging.error(f"A/B test failed: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"test_failed: {str(exc)}")

    @router.get("/v1/ab-tests/{test_id}/summary", tags=["admin"])
    async def get_ab_test_summary(test_id: str, request: Request):
        from app.core.ab_testing import ABTestRunner

        _require_admin(request)

        runner = ABTestRunner(db)
        summary = runner.get_test_summary(test_id)
        if not summary:
            raise HTTPException(status_code=404, detail="test_not_found")

        return {
            "test_id": summary.test_id,
            "variants": {"a": summary.variant_a, "b": summary.variant_b},
            "runs": {"total": summary.total_runs, "successful": summary.successful_runs},
            "average_metrics": {
                "a_duration_ms": round(summary.avg_a_duration_ms, 2),
                "b_duration_ms": round(summary.avg_b_duration_ms, 2),
                "a_tokens": round(summary.avg_a_tokens, 2),
                "b_tokens": round(summary.avg_b_tokens, 2),
            },
            "improvements": {
                "duration_pct": round(summary.avg_duration_improvement_pct, 2),
                "token_reduction_pct": round(summary.avg_token_reduction_pct, 2),
            },
            "win_rates": {
                "b_faster": summary.b_faster_count,
                "b_fewer_tokens": summary.b_fewer_tokens_count,
            },
            "recommendation": summary.recommended_winner,
        }

    @router.get("/v1/admin/rate-limits/{user_id}", tags=["admin"])
    async def get_user_rate_limits(user_id: str, request: Request):
        from app.core.rate_limiter import RateLimiter

        _require_admin(request)

        limiter = RateLimiter(db)
        limits = limiter.get_user_limits(user_id)
        return {"user_id": user_id, "limits": limits}

    @router.post("/v1/admin/rate-limits/{user_id}/reset", tags=["admin"])
    async def reset_user_rate_limits(
        user_id: str,
        request: Request,
        endpoint_category: Optional[str] = None,
    ):
        from app.core.rate_limiter import RateLimiter

        _require_admin(request)

        limiter = RateLimiter(db)
        limiter.reset_user_limits(user_id, endpoint_category)
        return {"status": "success", "user_id": user_id, "category": endpoint_category or "all"}

    @router.post("/v1/admin/rate-limits/cleanup", tags=["admin"])
    async def cleanup_rate_limits(request: Request):
        from app.core.rate_limiter import RateLimiter

        _require_admin(request)

        limiter = RateLimiter(db)
        limiter.cleanup_old_windows()
        return {"status": "success"}

    @router.get("/v1/admin/alerts", tags=["admin"])
    async def get_alerts(
        request: Request,
        active_only: bool = True,
        severity: Optional[str] = None,
        hours: int = 24,
    ):
        from app.infrastructure.monitoring.alerting import AlertSeverity, AlertingSystem

        _require_admin(request)

        alerting = AlertingSystem(db)
        if active_only:
            severity_filter = AlertSeverity(severity) if severity else None
            alerts = alerting.get_active_alerts(severity_filter)
        else:
            alerts = alerting.get_recent_alerts(hours=hours)

        return {
            "alerts": [
                {
                    "id": alert.id,
                    "type": alert.alert_type,
                    "severity": alert.severity,
                    "title": alert.title,
                    "message": alert.message,
                    "metadata": alert.metadata,
                    "created_at": alert.created_at,
                    "resolved_at": alert.resolved_at,
                    "resolved_by": alert.resolved_by,
                }
                for alert in alerts
            ],
            "total": len(alerts),
        }

    @router.post("/v1/admin/alerts/{alert_id}/resolve", tags=["admin"])
    async def resolve_alert(alert_id: int, request: Request):
        from app.infrastructure.monitoring.alerting import AlertingSystem

        ctx = _require_admin(request)

        alerting = AlertingSystem(db)
        alerting.resolve_alert(alert_id, ctx.user_id)
        return {"status": "success", "alert_id": alert_id}

    @router.post("/v1/admin/alerts/check", tags=["admin"])
    async def check_alerts(request: Request):
        from app.infrastructure.monitoring.alerting import AlertingSystem

        _require_admin(request)

        alerting = AlertingSystem(db)
        alerting.check_performance_degradation()
        return {"status": "success"}

    @router.post("/v1/admin/keys/{user_id}/revoke", tags=["admin"])
    async def revoke_user_key(user_id: str, request: Request, reason: str = "admin_revocation"):
        from app.key_management import revoke_api_key

        ctx = _require_admin(request)

        success = revoke_api_key(db, user_id, reason, ctx.user_id)
        if not success:
            raise HTTPException(status_code=404, detail="user_not_found")
        return {"status": "success", "user_id": user_id, "reason": reason}

    @router.post("/v1/keys/rotate", tags=["keys"])
    async def rotate_my_key(request: Request):
        from app.key_management import rotate_api_key

        ctx = authenticate(request, db)
        new_key = rotate_api_key(db, ctx.user_id, ctx.user_id)
        if not new_key:
            raise HTTPException(status_code=404, detail="user_not_found")
        return {
            "status": "success",
            "new_api_key": new_key,
            "message": "Store this key securely. Your old key is now invalid.",
        }

    @router.post("/v1/admin/keys/{user_id}/rotate", tags=["admin"])
    async def rotate_user_key(user_id: str, request: Request):
        from app.key_management import rotate_api_key

        ctx = _require_admin(request)

        new_key = rotate_api_key(db, user_id, ctx.user_id)
        if not new_key:
            raise HTTPException(status_code=404, detail="user_not_found")

        return {
            "status": "success",
            "user_id": user_id,
            "new_api_key": new_key,
            "message": "New key issued. User must update their configuration.",
        }

    @router.get("/v1/admin/keys/{user_id}/audit", tags=["admin"])
    async def get_key_audit(user_id: str, request: Request, limit: int = 50):
        from app.key_management import get_key_audit_log

        _require_admin(request)

        events = get_key_audit_log(db, user_id, limit)
        return {"user_id": user_id, "events": events, "total": len(events)}

    return router
