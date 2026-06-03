import requests
from datetime import datetime, timedelta
import pytest

from app.infrastructure.realtime.integrations.webhook_subscriptions import (
    InMemorySubscriptionStore,
    WebhookSubscription,
    WebhookSubscriptionService,
    HybridInboxService,
)


class FakeOutlookClient:
    def __init__(self, token="tok"):
        self._token = token

    def _get_valid_token(self, user_id: str):
        return self._token


class FakePollingService:
    def poll_inbox(self, user_id: str):
        return ["missed1", "missed2"]


def test_create_subscription_raises_on_graph_error(monkeypatch):
    store = InMemorySubscriptionStore()
    outlook = FakeOutlookClient()

    class FakeResp:
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("fail")

    def fake_post(url, json=None, headers=None):
        return FakeResp()

    monkeypatch.setattr(requests, 'post', fake_post)

    svc = WebhookSubscriptionService(outlook, None, "https://example.com", subscription_store=store)

    with pytest.raises(Exception):
        svc.create_subscription(user_id="user@test.com")


def test_delete_subscription_not_found_raises():
    svc = WebhookSubscriptionService(FakeOutlookClient(), None, "https://example.com", subscription_store=InMemorySubscriptionStore())
    with pytest.raises(ValueError):
        svc.delete_subscription("nope")


def test_renew_expiring_subscriptions_handles_partial_failure(monkeypatch):
    store = InMemorySubscriptionStore()

    # two subs
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

    svc = WebhookSubscriptionService(FakeOutlookClient(), None, "https://example.com", subscription_store=store)

    def fake_renew_ok(self, subscription_id):
        s = store.get(subscription_id)
        s.expires_at = datetime.now() + timedelta(hours=48)
        s.last_validated = datetime.now()
        store.update(s)
        return s

    def fake_renew_fail(self, subscription_id):
        raise RuntimeError("renew failed")

    # Make first succeed, second fail
    monkeypatch.setattr(WebhookSubscriptionService, 'renew_subscription', lambda self, sid: fake_renew_ok(self, sid) if sid.endswith('_0') else fake_renew_fail(self, sid))

    renewed = svc.renew_expiring_subscriptions()
    assert renewed == 1


def test_validate_notification_default_behavior():
    svc = WebhookSubscriptionService(FakeOutlookClient(), None, "https://example.com", subscription_store=InMemorySubscriptionStore())
    # Without client_secret, validation should be skipped/true
    assert svc._validate_notification({}) is True


def test_hybrid_inbox_fallback_to_polling_on_inactive(monkeypatch):
    store = InMemorySubscriptionStore()

    class FailingWebhookService:
        def create_subscription(self, user_id: str):
            raise RuntimeError("fail")

    polling = FakePollingService()
    hybrid = HybridInboxService(FailingWebhookService(), polling)

    # setup should catch exception and mark webhook inactive
    hybrid.setup_inbox_monitoring("user@test.com")
    assert hybrid.webhook_active.get("user@test.com") is False

    result = hybrid.poll_if_webhook_inactive("user@test.com")
    assert result == ["missed1", "missed2"]

