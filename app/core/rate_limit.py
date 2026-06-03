from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException

from app.core.interfaces.cache import AsyncCacheProtocol
from app.core.util import ns_key


@dataclass(frozen=True)
class RateState:
    # If >0, request should be delayed (switch to batch & not_before)
    delay_sec: int


# Lua script for atomic increment-and-check.
# Returns the counter value AFTER increment and sets TTL on first access.
_LUA_INCR_WITH_EXPIRE = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return current
"""


async def _incr_with_expire(r: AsyncCacheProtocol, key: str, ttl_sec: int) -> int:
    """Atomic INCR + EXPIRE via Lua to prevent race conditions."""
    if hasattr(r, "eval"):
        return int(await r.eval(_LUA_INCR_WITH_EXPIRE, 1, key, str(ttl_sec)))
    # Fallback for caches without eval (e.g. test stubs)
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.ttl(key)
    res = await pipe.execute()
    count = int(res[0])
    ttl = int(res[1])
    if ttl < 0:
        await r.expire(key, ttl_sec)
    return count


def _seconds_until_next_minute(now: float | None = None) -> int:
    t = int(now if now is not None else time.time())
    return 60 - (t % 60)


async def check_rate_limits(
    *,
    r: AsyncCacheProtocol,
    namespace: str,
    user_id: str,
    ip: str,
    soft_rpm: int,
    hard_rpm: int,
    hard_rps: int,
) -> RateState:
    """Enforce hard safety rails and return soft delay.

    - Soft RPM: if exceeded, do not block; return delay_sec until next minute.
    - Hard RPM / RPS: if exceeded, raise 429.
    """
    now = time.time()

    # Hard RPS (per user)
    if hard_rps > 0:
        sec_key = ns_key(namespace, "rl", "rps", user_id, str(int(now)))
        rps = await _incr_with_expire(r, sec_key, 2)
        if rps > hard_rps:
            raise HTTPException(status_code=429, detail="rate limit (rps)")

    # Hard RPM (per user)
    if hard_rpm > 0:
        minute_bucket = int(now // 60)
        rpm_key = ns_key(namespace, "rl", "rpm", user_id, str(minute_bucket))
        rpm = await _incr_with_expire(r, rpm_key, 120)
        if rpm > hard_rpm:
            raise HTTPException(status_code=429, detail="rate limit (rpm)")

        # Soft RPM
        if soft_rpm > 0 and rpm > soft_rpm:
            return RateState(delay_sec=_seconds_until_next_minute(now))

    # IP safety rail (hard only, 2x user limit)
    if hard_rpm > 0:
        minute_bucket = int(now // 60)
        ip_key = ns_key(namespace, "rl", "ip", ip or "unknown", str(minute_bucket))
        ip_rpm = await _incr_with_expire(r, ip_key, 120)
        if ip_rpm > (hard_rpm * 2):
            raise HTTPException(status_code=429, detail="rate limit (ip)")

    return RateState(delay_sec=0)
