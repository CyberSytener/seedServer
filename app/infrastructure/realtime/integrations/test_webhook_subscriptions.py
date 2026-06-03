import json
from datetime import datetime, timedelta, timezone
import uuid
import requests
import pytest

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

    # email_events.get_by_graph_message_id
    def get_by_graph_message_id(self, message_id):
        # Return a simple object
        class Obj:
            target_id = "target_123"
            campaign_id = "campaign_abc"
        return Obj()

    def create(self, **kwargs):
        # Store created reply event minimally
        self._created[kwargs.get('reply_id')] = kwargs
        return kwargs

    def update_status(self, _target_id, _status):
        self.updated = (_target_id, _status)

    def commit(self):
        self.committed = True


def test_inmemory_store_basic():
    store = InMemorySubscriptionStore()

    sub = WebhookSubscription(
        subscription_id=str(uuid.uuid4()),
        user_id="user@test.com",
        notification_url="https://example.com/webhooks/email/user@test.com",
        resource="/me/mailFolders('Inbox')/messages",
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(minutes=30),
    )

    store.create(sub)
    assert store.get(sub.subscription_id) is not None
    assert store.get_by_user("user@test.com")
    assert store.get_expiring_soon(hours=1)


def test_create_subscription_calls_graph_and_stores(monkeypatch):
    store = InMemorySubscriptionStore()
    outlook = FakeOutlookClient()
    repo = FakeRepo()

    fake_graph_response = {
        "id": "sub_1",
        "expirationDateTime": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat().replace('+00:00','Z'),
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return fake_graph_response

    def fake_post(url, json=None, headers=None):
        assert url.endswith('/subscriptions')
        return FakeResponse()

    monkeypatch.setattr(requests, 'post', fake_post)

    svc = WebhookSubscriptionService(outlook, repo, "https://example.com", subscription_store=store)

    sub = svc.create_subscription(user_id="user@test.com")
    assert sub.subscription_id == "sub_1"
    assert store.get(sub.subscription_id) is not None


def test_process_notification_unknown_subscription(monkeypatch):
    store = InMemorySubscriptionStore()
    outlook = FakeOutlookClient()
    repo = FakeRepo()

    svc = WebhookSubscriptionService(outlook, repo, "https://example.com", subscription_store=store)

    notification = {"value": [{"subscriptionId": "missing", "changeType": "created", "resourceData": {"id": "m1"}}]}
    processed = svc.process_notification(notification)

    assert processed == []


def test_process_notification_creates_reply_event(monkeypatch):
    store = InMemorySubscriptionStore()
    outlook = FakeOutlookClient()
    repo = FakeRepo()

    # Create and store a subscription
    sub_id = "sub_f"
    sub = WebhookSubscription(
        subscription_id=sub_id,
        user_id="user@test.com",
        notification_url="https://example.com/webhooks/email/user@test.com",
        resource="/me/messages('m1')",
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(hours=1),
    )
    store.create(sub)

    # Fake validate returns True by default (no client_secret)

    # Fake Graph GET for message to indicate a reply (inReplyTo set)
    class FakeGetResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "id": "m1",
                "subject": "Re: Hi",
                "inReplyTo": "orig_1",
                "receivedDateTime": (datetime.now(timezone.utc)).isoformat().replace('+00:00','Z'),
            }

    def fake_get(url, headers=None, params=None):
        assert 'me/messages/m1' in url
        return FakeGetResponse()

    monkeypatch.setattr(requests, 'get', fake_get)

    svc = WebhookSubscriptionService(outlook, repo, "https://example.com", subscription_store=store)

    notification = {"value": [{"subscriptionId": sub_id, "changeType": "created", "resourceData": {"id": "m1"}}]}
    processed = svc.process_notification(notification)

    assert processed == ["m1"]
    assert repo.committed is True
    assert getattr(repo, 'updated', None) == ("target_123", "replied")


def test_renew_subscription_patches_and_updates(monkeypatch):
    store = InMemorySubscriptionStore()
    outlook = FakeOutlookClient()
    repo = FakeRepo()

    sub_id = "sub_renew"
    sub = WebhookSubscription(
        subscription_id=sub_id,
        user_id="user@test.com",
        notification_url="https://example.com/webhooks/email/user@test.com",
        resource="/me/messages('m1')",
        created_at=datetime.now(),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    store.create(sub)

    # Fake patch response
    class FakePatchResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"expirationDateTime": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat().replace('+00:00','Z')}

    def fake_patch(url, json=None, headers=None):
        assert sub_id in url
        return FakePatchResp()

    monkeypatch.setattr(requests, 'patch', fake_patch)

    svc = WebhookSubscriptionService(outlook, repo, "https://example.com", subscription_store=store)
    renewed = svc.renew_subscription(sub_id)

    # The renewed expiration comes back as an aware datetime (from ISO +00:00)
    assert renewed.expires_at.tzinfo is not None
    # Renewal recorded a last_validated timestamp on the stored subscription
    assert store.get(sub_id).last_validated is not None

