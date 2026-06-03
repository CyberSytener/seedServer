"""FastAPI Depends() providers for core services.

Usage in any router::

    from app.dependencies import get_db, get_redis, get_settings_dep, get_hub

    @router.get("/example")
    async def example(db: DB = Depends(get_db)):
        ...
"""
from __future__ import annotations

from fastapi import Request

from app.infrastructure.db.sqlite import DB
from app.settings import Settings


def get_db(request: Request) -> DB:
    """Resolve the SQLite DB from app state."""
    return request.app.state.seed.db


def get_redis(request: Request):
    """Resolve the Redis client from app state."""
    return request.app.state.seed.redis


def get_settings_dep(request: Request) -> Settings:
    """Resolve the Settings dataclass from app state."""
    return request.app.state.seed.settings


def get_hub(request: Request):
    """Resolve the RedisQueueHub from app state."""
    return request.app.state.seed.queuehub


def get_broker(request: Request):
    """Resolve the RedisEventBroker from app state."""
    return request.app.state.seed.broker
