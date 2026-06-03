import time
from datetime import datetime, timedelta
import uuid
import requests

from app.infrastructure.realtime.integrations.webhook_subscriptions import (
    InMemorySubscriptionStore,
    WebhookSubscription,
    WebhookSubscriptionService,
)


class FakeOutlookClient:
    def __init__(self, token="tok"):
        self._token = token

    def _get_valid_token(self, user_id: str):
        return self._token


class FakeRepo:
    def __init__(self):
        self.email_events = self
        self.reply_events = self
        self.targets = self
        self._created = {}

    def get_by_graph_message_id(self, message_id):
        class Obj:
            target_id = "target_123"
            campaign_id = "campaign_abc"
        return Obj()

    def create(self, **kwargs):
        self._created[kwargs.get('reply_id')] = kwargs
        return kwargs

    def update_status(self, _target_id, _status):
        self.updated = (_target_id, _status)

    def commit(self):
        self.committed = True


def test_validation_tokens_handled_gracefully():
    store = InMemorySubscriptionStore()
    outlook = FakeOutlookClient()
    repo = FakeRepo()

    svc = WebhookSubscriptionService(outlook, repo, "https://example.com", subscription_store=store)

    notification = {"validationTokens": ["token1"]}
    processed = svc.process_notification(notification)

    assert processed == []


def test_invalid_signature_skips_notification(monkeypatch):
    store = InMemorySubscriptionStore()
    outlook = FakeOutlookClient()
    repo = FakeRepo()

    sub_id = "sub_bad"
    sub = WebhookSubscription(
        subscription_id=sub_id,
        user_id="user@test.com",
        notification_url="https://example.com/webhooks/email/user@test.com",
        resource="/me/messages('m1')",
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(hours=1),
    )
    store.create(sub)

    svc = WebhookSubscriptionService(outlook, repo, "https://example.com", subscription_store=store, client_secret="s")

    # Force validation to fail
    monkeypatch.setattr(WebhookSubscriptionService, "_validate_notification", lambda self, n: False)

    notification = {"value": [{"subscriptionId": sub_id, "changeType": "created", "resourceData": {"id": "m1"}}]}
    processed = svc.process_notification(notification)

    assert processed == []


def test_renew_expiring_subscriptions_calls_renew_and_counts(monkeypatch):
    store = InMemorySubscriptionStore()

    # create two expiring subscriptions
    for i in range(2):
        sub = WebhookSubscription(
            subscription_id=f"sub_{i}",
            user_id=f"user{i}@test.com",
            notification_url=f"https://example.com/webhooks/email/user{i}@test.com",
            resource="/me/messages",
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=30),
        )
        store.create(sub)

    outlook = FakeOutlookClient()
    repo = FakeRepo()
    svc = WebhookSubscriptionService(outlook, repo, "https://example.com", subscription_store=store)

    calls = {"count": 0}

    def fake_renew(self, subscription_id):
        calls["count"] += 1
        s = store.get(subscription_id)
        s.expires_at = datetime.now() + timedelta(hours=48)
        s.last_validated = datetime.now()
        store.update(s)
        return s

    monkeypatch.setattr(WebhookSubscriptionService, "renew_subscription", fake_renew)

    renewed = svc.renew_expiring_subscriptions()
    assert renewed == 2
    assert calls["count"] == 2


def test_delete_subscription_calls_graph_and_removes(monkeypatch):
    store = InMemorySubscriptionStore()

    sub_id = "sub_del"
    sub = WebhookSubscription(
        subscription_id=sub_id,
        user_id="user@test.com",
        notification_url="https://example.com/webhooks/email/user@test.com",
        resource="/me/messages('m1')",
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(hours=1),
    )
    store.create(sub)

    outlook = FakeOutlookClient()
    repo = FakeRepo()
    svc = WebhookSubscriptionService(outlook, repo, "https://example.com", subscription_store=store)

    class FakeDelResp:
        def raise_for_status(self):
            pass

    def fake_delete(url, headers=None):
        assert sub_id in url
        return FakeDelResp()

    monkeypatch.setattr(requests, 'delete', fake_delete)

    svc.delete_subscription(sub_id)
    assert store.get(sub_id) is None

