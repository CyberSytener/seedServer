import json
from datetime import datetime, timezone

from app.api.ws.session import SimpleRedisSessionStore


class MockRedis:
    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def lpush(self, key, value):
        self.store.setdefault(key, [])
        self.store[key].insert(0, value)

    def ltrim(self, key, start, end):
        if key in self.store and isinstance(self.store[key], list):
            self.store[key] = self.store[key][start:end+1]

    def expire(self, key, ttl):
        pass

    def lrange(self, key, start, end):
        return self.store.get(key, [])

    def delete(self, key):
        if key in self.store:
            del self.store[key]


def test_create_and_get_session():
    mock_redis = MockRedis()
    store = SimpleRedisSessionStore(mock_redis)

    sid = store.create_session("user1", metadata={"foo": "bar"})
    data = store.get_session(sid)
    assert data is not None
    assert data["user_id"] == "user1"
    assert data["foo"] == "bar"

    # created_at and last_activity are ISO strings with timezone
    created = datetime.fromisoformat(data["created_at"])
    last = datetime.fromisoformat(data["last_activity"])
    assert created.tzinfo is not None
    assert last.tzinfo is not None


def test_update_activity_updates_timestamp():
    mock_redis = MockRedis()
    store = SimpleRedisSessionStore(mock_redis)

    sid = store.create_session("user2")
    before = datetime.fromisoformat(store.get_session(sid)["last_activity"])    

    store.update_activity(sid)
    after = datetime.fromisoformat(store.get_session(sid)["last_activity"])    

    assert after >= before
    assert after.tzinfo is not None


def test_queue_and_get_pending_messages():
    mock_redis = MockRedis()
    store = SimpleRedisSessionStore(mock_redis)

    sid = store.create_session("user3")
    store.queue_message(sid, {"m": 1})
    store.queue_message(sid, {"m": 2})

    msgs = store.get_pending_messages(sid)
    assert len(msgs) == 2
    assert msgs[0]["m"] == 1  # chronological order
    assert msgs[1]["m"] == 2

