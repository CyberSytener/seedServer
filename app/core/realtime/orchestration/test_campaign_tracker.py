from datetime import datetime, timedelta
from app.core.realtime.orchestration.campaign_tracker import (
    CampaignTracker,
    CampaignManager,
    EventType,
    TargetStatus,
)


def test_campaign_flow_and_progress():
    c = CampaignTracker.create("t1", "c1", "Test Campaign", target_count=2)
    c.add_target("cand1", "a@x.com")
    c.add_target("cand2", "b@x.com")

    # Send email to cand1
    evt1 = c.record_event(EventType.EMAIL_SENT, "cand1")
    assert evt1.event_type == EventType.EMAIL_SENT

    # Receive reply
    evt2 = c.record_event(EventType.REPLY_RECEIVED, "cand1")
    assert c.get_target_progress("cand1")["stage"] >= 2

    # Schedule interview
    evt3 = c.record_event(EventType.INTERVIEW_SCHEDULED, "cand1")
    assert c.get_target_progress("cand1")["stage"] == 4

    # Edit email (manual override)
    evt_edit = c.edit_email("cand2", "email_2", "Old", "New", "o", "n", "rec", "typo")
    assert evt_edit.manual_override is True

    # Progress summary
    prog = c.get_progress()
    assert prog["campaign_id"] == "c1"

    # Timeline
    tl = c.get_timeline("cand1")
    assert tl["target_id"] == "cand1"


def test_campaign_manager_collections():
    mgr = CampaignManager()
    mgr.create_campaign("t1", "cA", "Camp A", 10)
    mgr.create_campaign("t1", "cB", "Camp B", 5)

    assert mgr.get_campaign("cA") is not None
    assert len(mgr.get_tenant_campaigns("t1")) == 2
