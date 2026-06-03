"""
Quick smoke tests for PHASE 3 components (in-memory checks, no external APIs)
Run locally to validate that core modules import and basic behaviors work.

Usage:
    python scripts/smoke_phase3_checks.py

Exits with code 0 if all checks pass, non-zero otherwise.
"""

import sys
import traceback

SUCCESS = True

checks = []


def ok(name):
    print(f"✅ {name}")


def fail(name, exc=None):
    global SUCCESS
    SUCCESS = False
    print(f"❌ {name}")
    if exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__)


# ---------------------------------------------------------------------------
# 1) AdvancedReplyParser basic parsing
# ---------------------------------------------------------------------------
try:
    from app.infrastructure.realtime.integrations.advanced_reply_parser import (
        AdvancedReplyParser,
        ParseStrategy,
        InterestLevel,
    )

    p = AdvancedReplyParser(strategy=ParseStrategy.REGEX)
    r1 = p.parse_reply("I'm very interested — let's schedule a call!")
    assert r1.interest_level in (InterestLevel.HIGH, InterestLevel.NEUTRAL, InterestLevel.UNKNOWN)

    p.strategy = ParseStrategy.SENTIMENT
    r2 = p.parse_reply("No thanks, not interested at this time")
    assert r2.interest_level in (InterestLevel.LOW, InterestLevel.NEUTRAL)

    p.strategy = ParseStrategy.HYBRID
    r3 = p.parse_reply("I might be interested, need more info")

    ok("AdvancedReplyParser: basic parse checks")
except Exception as e:
    fail("AdvancedReplyParser: basic parse checks", e)


# ---------------------------------------------------------------------------
# 2) QuotaManager checks
# ---------------------------------------------------------------------------
try:
    from app.core.realtime.orchestration.multi_tenant_quotas import QuotaManager, OperationType

    qm = QuotaManager()
    qm.set_quota("tenant_test", emails_per_day=5, emails_per_hour=2, llm_cost_per_month=10.0)
    allowed, reason = qm.check_quota("tenant_test", OperationType.SEND_EMAIL)
    assert allowed
    qm.record_usage("tenant_test", OperationType.SEND_EMAIL, quantity=1)

    # Exceed hourly quota
    qm.record_usage("tenant_test", OperationType.SEND_EMAIL, quantity=2)
    allowed2, reason2 = qm.check_quota("tenant_test", OperationType.SEND_EMAIL)

    ok("QuotaManager: set/check/record usage")
except Exception as e:
    fail("QuotaManager: set/check/record usage", e)


# ---------------------------------------------------------------------------
# 3) CampaignTracker checks
# ---------------------------------------------------------------------------
try:
    from app.core.realtime.orchestration.campaign_tracker import CampaignTracker, EventType

    c = CampaignTracker.create("tenant_x", "camp_1", "Test Campaign", 3)
    c.add_target("t1", "a@a.com")
    c.add_target("t2", "b@b.com")

    c.record_event(EventType.EMAIL_SENT, "t1", actor="system", data={"email_id": "m1"})
    c.record_event(EventType.REPLY_RECEIVED, "t1", actor="candidate", data={"interest_level": "high"})

    progress = c.get_progress()
    assert progress["progress"]["engaged"] >= 1

    timeline = c.get_timeline("t1")
    assert "timeline" in timeline

    ok("CampaignTracker: create/record/get progress")
except Exception as e:
    fail("CampaignTracker: create/record/get progress", e)


# ---------------------------------------------------------------------------
# 4) FeatureFlags checks
# ---------------------------------------------------------------------------
try:
    from app.core.realtime.orchestration.feature_flags import FeatureFlags

    ff = FeatureFlags()
    # Deterministic check (no error)
    v = ff.is_enabled("mail_provider_gmail", tenant_id="tenant_test")

    ff.enable_for_tenant("mail_provider_gmail", "tenant_test")
    assert ff.is_enabled("mail_provider_gmail", tenant_id="tenant_test") is True

    ok("FeatureFlags: basic operations")
except Exception as e:
    fail("FeatureFlags: basic operations", e)


# ---------------------------------------------------------------------------
# 5) ChaosExperiment sanity checks
# ---------------------------------------------------------------------------
try:
    from app.core.realtime.orchestration.chaos_framework import ChaosExperiment

    ch = ChaosExperiment(name="smoke", description="smoke test", target_tenant="tenant_test", duration_seconds=1)
    ch.start()
    ev = ch.inject_worker_failure("worker_smoke")
    assert isinstance(ev.event_id, str)

    ok("ChaosExperiment: inject_worker_failure smoke")
except Exception as e:
    fail("ChaosExperiment: inject_worker_failure smoke", e)


# ---------------------------------------------------------------------------
# 6) Webhook subscription store (in-memory) checks
# ---------------------------------------------------------------------------
try:
    from app.infrastructure.realtime.integrations.webhook_subscriptions import InMemorySubscriptionStore, WebhookSubscription
    from datetime import datetime, timedelta

    store = InMemorySubscriptionStore()
    s = WebhookSubscription(
        subscription_id="sub1",
        user_id="u1",
        notification_url="https://example.com/n1",
        resource="/me/mailFolders('Inbox')/messages",
        created_at=datetime.now(),
        expires_at=datetime.now() + timedelta(hours=1),
    )
    store.create(s)
    assert store.get("sub1") is not None
    ex = store.get_expiring_soon(hours=2)
    assert len(ex) >= 1

    ok("Webhook InMemorySubscriptionStore: create/get/expiring")
except Exception as e:
    fail("Webhook InMemorySubscriptionStore: create/get/expiring", e)


# ---------------------------------------------------------------------------
# 7) OutlookEmailClient basic instantiation + auth URL
# ---------------------------------------------------------------------------
try:
    from app.infrastructure.realtime.integrations.outlook_email_client import OutlookEmailClient, InMemoryTokenStore

    t = InMemoryTokenStore()
    client = OutlookEmailClient(client_id="id", client_secret="secret", tenant_id="common", token_store=t)
    url = client.get_authorization_url(redirect_uri="https://example.com/cb")
    assert "authorize" in url

    ok("OutlookEmailClient: instantiation + auth URL")
except Exception as e:
    fail("OutlookEmailClient: instantiation + auth URL", e)


# ---------------------------------------------------------------------------
# Finish
# ---------------------------------------------------------------------------
if SUCCESS:
    print("\nALL SMOKE CHECKS PASSED")
    sys.exit(0)
else:
    print("\nSOME SMOKE CHECKS FAILED")
    sys.exit(2)

