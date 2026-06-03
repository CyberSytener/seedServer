from datetime import datetime, timedelta, timezone
import requests
import pytest

from app.infrastructure.realtime.integrations.outlook_email_client import (
    OutlookEmailClient,
    InMemoryTokenStore,
)
from app.infrastructure.realtime.integrations.outlook_email_client import EmailMetadata


def test_get_authorization_url_contains_client_and_redirect():
    client = OutlookEmailClient(client_id="id123", client_secret="sec")
    url = client.get_authorization_url(redirect_uri="https://app/cb", state="s")
    assert "id123" in url
    assert "https://app/cb" in url


def test_exchange_code_for_token_stores_token(monkeypatch, tmp_path):
    store = InMemoryTokenStore()
    client = OutlookEmailClient(client_id="id", client_secret="sec", token_store=store)

    fake_response = {
        "access_token": "atk",
        "refresh_token": "rtk",
        "expires_in": 3600,
    }

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return fake_response

    def fake_post(url, data=None):
        assert "/token" in url
        return FakeResp()

    monkeypatch.setattr(requests, 'post', fake_post)

    token = client.exchange_code_for_token(code="c", redirect_uri="https://app/cb", user_id="u@x")
    assert token == "atk"
    assert store.get_token("u@x") is not None


def test_refresh_token_path(monkeypatch):
    store = InMemoryTokenStore()
    store.set_refresh_token("u@x", "rtk")
    client = OutlookEmailClient(client_id="id", client_secret="sec", token_store=store)

    fake_response = {
        "access_token": "atk2",
        "refresh_token": "rtk2",
        "expires_in": 3600,
    }

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return fake_response

    def fake_post(url, data=None):
        return FakeResp()

    monkeypatch.setattr(requests, 'post', fake_post)

    # No token currently, so _get_valid_token should trigger refresh flow
    token = client._get_valid_token("u@x")
    assert token == "atk2"
    assert store.get_refresh_token("u@x") == "rtk2"


def test_send_email_success_and_failure(monkeypatch):
    store = InMemoryTokenStore()
    store.set_token("u@x", "tok", datetime.now(timezone.utc) + timedelta(hours=1))
    client = OutlookEmailClient(client_id="id", client_secret="sec", token_store=store)

    class FakeRespOK:
        def raise_for_status(self):
            pass

    class FakeRespFail:
        def raise_for_status(self):
            raise requests.exceptions.RequestException("boom")

    def fake_post_ok(url, json=None, headers=None):
        return FakeRespOK()

    def fake_post_fail(url, json=None, headers=None):
        return FakeRespFail()

    monkeypatch.setattr(requests, 'post', fake_post_ok)
    res = client.send_email("u@x", ["a@b.com"], "s", "b")
    assert res.status == "sent"

    monkeypatch.setattr(requests, 'post', fake_post_fail)
    res2 = client.send_email("u@x", ["a@b.com"], "s", "b")
    assert res2.status == "failed"


def test_get_inbox_delta_parses_emails_and_stores_token(monkeypatch):
    store = InMemoryTokenStore()
    store.set_token("u@x", "tok", datetime.now(timezone.utc) + timedelta(hours=1))
    client = OutlookEmailClient(client_id="id", client_secret="sec", token_store=store)

    sample_item = {
        "id": "m1",
        "subject": "Hi",
        "from": {"emailAddress": {"address": "from@x"}},
        "toRecipients": [{"emailAddress": {"address": "to@x"}}],
        "receivedDateTime": (datetime.now(timezone.utc)).isoformat().replace('+00:00','Z'),
        "isRead": False,
        "importance": "normal",
        "bodyPreview": "preview",
        "hasAttachments": False,
    }

    class FakeGet:
        def raise_for_status(self):
            pass

        def json(self):
            return {"value": [sample_item], "@odata.deltaLink": "https://...$deltaToken=newtoken"}

    def fake_get(url, params=None, headers=None):
        return FakeGet()

    monkeypatch.setattr(requests, 'get', fake_get)
    result = client.get_inbox_delta("u@x")

    assert result.emails and isinstance(result.emails[0], EmailMetadata)
    assert store.get_delta_token("u@x") == "newtoken"

