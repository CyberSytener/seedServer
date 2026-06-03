from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import redis.asyncio as redis

from app.core.policy import Usage
from .redisutil import ns_key


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def get_usage(r: redis.Redis, namespace: str, user_id: str) -> Usage:
    day = _day_key()
    month = _month_key()
    day_h = ns_key(namespace, "usage", "day", user_id, day)
    month_h = ns_key(namespace, "usage", "month", user_id, month)

    pipe = r.pipeline()
    pipe.hget(day_h, "fast")
    pipe.hget(day_h, "actions")
    pipe.hget(month_h, "actions")
    res = await pipe.execute()

    fast_used = int(res[0] or 0)
    actions_used_day = int(res[1] or 0)
    actions_used_month = int(res[2] or 0)
    return Usage(fast_used_today=fast_used, actions_used_today=actions_used_day, actions_used_month=actions_used_month)


async def bump_usage(
    r: redis.Redis,
    namespace: str,
    user_id: str,
    *,
    inc_actions: int = 1,
    inc_fast: int = 0,
) -> None:
    day = _day_key()
    month = _month_key()
    day_h = ns_key(namespace, "usage", "day", user_id, day)
    month_h = ns_key(namespace, "usage", "month", user_id, month)

    pipe = r.pipeline()
    if inc_fast:
        pipe.hincrby(day_h, "fast", inc_fast)
    if inc_actions:
        pipe.hincrby(day_h, "actions", inc_actions)
        pipe.hincrby(month_h, "actions", inc_actions)

    # expiry: keep 2 days and 45 days
    pipe.expire(day_h, 2 * 24 * 3600)
    pipe.expire(month_h, 45 * 24 * 3600)
    await pipe.execute()
