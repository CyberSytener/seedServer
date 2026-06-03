from datetime import datetime, timedelta
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
    def get_by_graph_message_id(self, message_id):
        return None

    def create(self, **kwargs):
        return kwargs

    def update_status(self, _target_id, _status):
        pass

    def commit(self):
        pass


def test_updated_event_does_not_create_reply(monkeypatch):
    store = InMemorySubscriptionStore()
    sub_id = "sub_upd"
    sub = WebhookSubscription(
        subscription_id=sub_id,
        user_id="user@test.com",
        notification_url="https://example.com/webhooks/email/user@test.com",
        resource="/me/messages('m1')",
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(hours=1),
    )
    store.create(sub)

    svc = WebhookSubscriptionService(FakeOutlookClient(), FakeRepo(), "https://example.com", subscription_store=store)

    notification = {"value": [{"subscriptionId": sub_id, "changeType": "updated", "resource": "/me/messages('m1')", "resourceData": {}}]}
    processed = svc.process_notification(notification)

    # 'updated' should not create reply events
    assert processed == []


def test_notification_missing_resource_data_skips(monkeypatch):
    store = InMemorySubscriptionStore()
    sub_id = "sub_missing"
    sub = WebhookSubscription(
        subscription_id=sub_id,
        user_id="user@test.com",
        notification_url="https://example.com/webhooks/email/user@test.com",
        resource="/me/messages('m1')",
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(hours=1),
    )
    store.create(sub)

    svc = WebhookSubscriptionService(FakeOutlookClient(), FakeRepo(), "https://example.com", subscription_store=store)

    # resourceData missing -> should be skipped
    notification = {"value": [{"subscriptionId": sub_id, "changeType": "created", "resource": "/me/messages('m1')"}]}
    processed = svc.process_notification(notification)

    assert processed == []


def test_lifecycle_notification_handling_when_present():
    store = InMemorySubscriptionStore()
    svc = WebhookSubscriptionService(FakeOutlookClient(), FakeRepo(), "https://example.com", subscription_store=store)

    # Lifecycle/ping-type payload contains validationTokens key or lifecycle specifics; ensure handled gracefully
    notification = {"validationTokens": ["abc"], "value": []}
    processed = svc.process_notification(notification)

    assert processed == []

