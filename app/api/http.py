"""HTTP endpoints for basic action operations."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import authenticate
from app.core.realtime.pending_store import RedisPendingActionStore
from app.dependencies import get_db, get_redis
from app.infrastructure.db.sqlite import DB
from app.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["actions"])


@router.get("/actions/pending")
async def list_pending_actions(
    request: Request,
    limit: int = 50,
    db: DB = Depends(get_db),
    redis_client=Depends(get_redis),
):
    """List pending/deferred actions for the authenticated user."""
    ctx = authenticate(request, db)

    if redis_client is None:
        raise HTTPException(status_code=503, detail="redis_unavailable")

    settings = get_settings()
    store = RedisPendingActionStore(
        redis_client,
        namespace=f"{settings.redis_namespace}:pending_actions",
    )

    pending = await store.list_pending_for_user(ctx.user_id, limit=limit)
    return {"user_id": ctx.user_id, "items": pending, "count": len(pending)}
