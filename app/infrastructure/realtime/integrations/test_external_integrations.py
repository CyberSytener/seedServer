import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from app.infrastructure.realtime.integrations.webhook_subscriptions import (
    WebhookSubscriptionService,
    InMemorySubscriptionStore,
    WebhookSubscription,
)
from app.infrastructure.realtime.integrations.outlook_email_client import OutlookEmailClient, InMemoryTokenStore
from app.infrastructure.realtime.integrations.advanced_reply_parser import AdvancedReplyParser, ParseStrategy, InterestLevel


class DummyRepo:
    def __init__(self):
        self.email_events = MagicMock()
        self.reply_events = MagicMock()
        self.targets = MagicMock()
        self._committed = False

    def commit(self):
        self._committed = True


def test_outlook_send_email_posts_to_graph():
    # Arrange
    token_store = InMemoryTokenStore()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    token_store.set_token("user@company.com", "fake-token", expires)

    client = OutlookEmailClient("id", "secret", tenant_id="common", token_store=token_store)

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    with patch("requests.post", return_value=mock_response) as post:
        # Act
        res = client.send_email(
            user_id="user@company.com",
            to=["to@example.com"],
            subject="Hello",
            body="Body",
            idempotency_key="key-1",
        )

        # Assert
        assert res.status == "sent"
        post.assert_called_once()


def test_create_subscription_stores_subscription():
    # Arrange
    token_store = InMemoryTokenStore()
    token_store.set_token("recruiter@company.com", "tok", datetime.now(timezone.utc) + timedelta(hours=1))
    outlook = OutlookEmailClient("id", "secret", token_store=token_store)

    store = InMemorySubscriptionStore()

    graph_resp = MagicMock()
    graph_resp.raise_for_status.return_value = None
    graph_resp.json.return_value = {
        "id": "sub-123",
        "expirationDateTime": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat().replace('+00:00','Z'),
    }

    with patch("requests.post", return_value=graph_resp) as post:
        svc = WebhookSubscriptionService(outlook, repository_service=None, webhook_base_url="https://example.com", subscription_store=store)
        sub = svc.create_subscription(user_id="recruiter@company.com")

        assert sub.subscription_id == "sub-123"
        assert store.get("sub-123") is not None
        post.assert_called_once()


def test_process_new_email_creates_reply_event():
    # Arrange
    token_store = InMemoryTokenStore()
    token_store.set_token("recruiter@company.com", "tok", datetime.now(timezone.utc) + timedelta(hours=1))
    outlook = OutlookEmailClient("id", "secret", token_store=token_store)

    repo = DummyRepo()

    # Original email record
    original_email = MagicMock()
    original_email.target_id = "target-1"
    original_email.campaign_id = "campaign-1"
    original_email.graph_message_id = "orig-msg-1"

    repo.email_events.get_by_graph_message_id.return_value = original_email

    # Graph message payload for new message (a reply)
    email_payload = {
        "id": "msg-2",
        "subject": "Re: Opportunity",
        "inReplyTo": "orig-msg-1",
        "receivedDateTime": (datetime.now(timezone.utc)).isoformat().replace('+00:00','Z'),
    }

    get_resp = MagicMock()
    get_resp.raise_for_status.return_value = None
    get_resp.json.return_value = email_payload

    with patch("requests.get", return_value=get_resp) as get:
        svc = WebhookSubscriptionService(outlook, repository_service=repo, webhook_base_url="https://example.com")
        svc._process_new_email("recruiter@company.com", "msg-2")

        # reply_events.create called
        assert repo.reply_events.create.called
        # target status updated
        repo.targets.update_status.assert_called_with("target-1", "replied")
        assert repo._committed


def test_parser_llm_strategy_fallback_and_llm_usage():
    parser = AdvancedReplyParser(strategy=ParseStrategy.LLM)

    # When no llm_client provided, should fallback to sentiment parse without exception
    res = parser.parse_reply("No thanks, not interested")
    assert res.interest_level in (InterestLevel.LOW, InterestLevel.NEUTRAL)

    # Provide a fake llm client - although current LLM code uses placeholder, ensure integration path works
    class FakeLLM:
        def complete(self, prompt: str):
            return {"interest_level": "high", "confidence": 0.9, "reasoning": "positive"}

    res2 = parser._parse_llm("I am very interested", FakeLLM())
    assert res2.interest_level == InterestLevel.HIGH
    assert res2.confidence > 0.8

