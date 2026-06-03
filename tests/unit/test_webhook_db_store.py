"""Tests for DatabaseSubscriptionStore (SQLite-backed webhook persistence)."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.infrastructure.realtime.integrations.webhook_subscriptions import (
    DatabaseSubscriptionStore,
    WebhookSubscription,
)


class _FakeDB:
    """Minimal SQLite wrapper matching the DatabaseProtocol interface."""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.execute(sql, params)
        self._conn.commit()

    def fetchone(self, sql: str, params: tuple = ()):
        return self._conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list:
        return self._conn.execute(sql, params).fetchall()

    def close(self):
        self._conn.close()


def _make_sub(
    *,
    user_id: str = "user@test.com",
    hours_until_expiry: int = 24,
) -> WebhookSubscription:
    return WebhookSubscription(
        subscription_id=str(uuid.uuid4()),
        user_id=user_id,
        notification_url=f"https://app.example.com/webhooks/email/{user_id}",
        resource="/me/mailFolders('Inbox')/messages",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=hours_until_expiry),
        is_active=True,
        validation_token=str(uuid.uuid4()),
    )


@pytest.fixture()
def store():
    # Reset class-level flag so each test gets a fresh table
    DatabaseSubscriptionStore._TABLE_CREATED = False
    db = _FakeDB()
    s = DatabaseSubscriptionStore(db)
    yield s
    db.close()


# ------------------------------------------------------------------
# CRUD basics
# ------------------------------------------------------------------

def test_create_and_get(store: DatabaseSubscriptionStore):
    sub = _make_sub()
    store.create(sub)
    got = store.get(sub.subscription_id)
    assert got is not None
    assert got.subscription_id == sub.subscription_id
    assert got.user_id == sub.user_id
    assert got.notification_url == sub.notification_url
    assert got.resource == sub.resource
    assert got.is_active is True
    assert got.validation_token == sub.validation_token


def test_get_nonexistent_returns_none(store: DatabaseSubscriptionStore):
    assert store.get("nonexistent-id") is None


def test_get_by_user(store: DatabaseSubscriptionStore):
    sub1 = _make_sub(user_id="alice@example.com")
    sub2 = _make_sub(user_id="alice@example.com")
    sub3 = _make_sub(user_id="bob@example.com")

    store.create(sub1)
    store.create(sub2)
    store.create(sub3)

    alice_subs = store.get_by_user("alice@example.com")
    assert len(alice_subs) == 2
    assert {s.subscription_id for s in alice_subs} == {
        sub1.subscription_id,
        sub2.subscription_id,
    }

    bob_subs = store.get_by_user("bob@example.com")
    assert len(bob_subs) == 1


def test_update(store: DatabaseSubscriptionStore):
    sub = _make_sub()
    store.create(sub)

    new_expires = datetime.now(timezone.utc) + timedelta(hours=48)
    sub.expires_at = new_expires
    sub.last_validated = datetime.now(timezone.utc)
    sub.is_active = False
    store.update(sub)

    got = store.get(sub.subscription_id)
    assert got is not None
    assert got.is_active is False
    assert got.last_validated is not None
    # ISO round-trip may lose microsecond precision; compare to the second
    assert got.expires_at.replace(microsecond=0) == new_expires.replace(microsecond=0)


def test_delete(store: DatabaseSubscriptionStore):
    sub = _make_sub()
    store.create(sub)

    store.delete(sub.subscription_id)
    assert store.get(sub.subscription_id) is None


def test_delete_nonexistent_is_noop(store: DatabaseSubscriptionStore):
    # Should not raise
    store.delete("does-not-exist")


# ------------------------------------------------------------------
# Expiry queries
# ------------------------------------------------------------------

def test_get_expiring_soon(store: DatabaseSubscriptionStore):
    soon = _make_sub(hours_until_expiry=0)  # expires now
    soon.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    later = _make_sub(hours_until_expiry=24)
    inactive = _make_sub(hours_until_expiry=0)
    inactive.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    inactive.is_active = False

    store.create(soon)
    store.create(later)
    store.create(inactive)

    expiring = store.get_expiring_soon(hours=1)
    ids = {s.subscription_id for s in expiring}
    assert soon.subscription_id in ids
    assert later.subscription_id not in ids
    # inactive subs should be excluded
    assert inactive.subscription_id not in ids


def test_get_expiring_soon_empty(store: DatabaseSubscriptionStore):
    assert store.get_expiring_soon(hours=1) == []


# ------------------------------------------------------------------
# Table idempotency
# ------------------------------------------------------------------

def test_table_creation_is_idempotent():
    """Calling _ensure_table twice doesn't raise."""
    DatabaseSubscriptionStore._TABLE_CREATED = False
    db = _FakeDB()
    s1 = DatabaseSubscriptionStore(db)
    DatabaseSubscriptionStore._TABLE_CREATED = False
    s2 = DatabaseSubscriptionStore(db)
    # Both should work fine
    sub = _make_sub()
    s1.create(sub)
    assert s2.get(sub.subscription_id) is not None
    db.close()
