import json
from app.core.realtime.redis_idempotency import NoOpRedisIdempotencyManager, RedisIdempotencyManager


def test_noop_manager_basic():
    m = NoOpRedisIdempotencyManager()
    called = {"n": 0}
    def fn():
        called["n"] += 1
        return {"x": called["n"]}

    r1 = m.get_or_execute("a1", fn)
    r2 = m.get_or_execute("a1", fn)
    assert r1 == r2
    assert called["n"] == 1

    m.invalidate("a1")
    r3 = m.get_or_execute("a1", fn)
    assert called["n"] == 2
    assert m.stats()["cached_actions"] == 1


class FakeRedis:
    def __init__(self):
        self.store = {}
    def register_script(self, script):
        return lambda *a, **k: None
    def get(self, k):
        return self.store.get(k)
    def set(self, k, v, ex=None):
        # store bytes to simulate real redis
        if isinstance(v, str):
            self.store[k] = v
        else:
            self.store[k] = v
    def delete(self, *keys):
        for k in keys:
            if k in self.store:
                del self.store[k]
    def keys(self, pattern):
        return [k.encode() if isinstance(k, str) else k for k in self.store.keys()]


def test_redis_manager_cache_and_force_reexecute():
    fake = FakeRedis()
    m = RedisIdempotencyManager(fake, ttl_seconds=10)

    def fn():
        return {"ok": True}

    # first call should execute and cache
    r1 = m.get_or_execute("act1", fn)
    assert r1 == {"ok": True}

    # simulate cache hit by prepopulating result key
    res_key = m._key("act1", "result")
    fake.store[res_key] = json.dumps({"ok": True})

    r2 = m.get_or_execute("act1", fn)
    assert r2 == {"ok": True}

    # force reexecute should call fn again and overwrite cache
    called = {"n": 0}
    def fn2():
        called["n"] += 1
        return {"n": called["n"]}
    r3 = m.get_or_execute("act1", fn2, force_reexecute=True)
    assert r3 == {"n": 1}
    # cached value should be updated
    assert json.loads(fake.store[res_key]) == {"n": 1}
    stats = m.stats()
    assert "total_keys" in stats
    assert stats["prefix"] == m.prefix

