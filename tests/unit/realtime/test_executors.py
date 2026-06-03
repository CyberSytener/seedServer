import pytest
from datetime import datetime

from app.core.realtime.executors import (
    SearchListingsExecutor,
    GetListingDetailsExecutor,
    BookViewingExecutor,
    CreateOrUpdateCVExecutor,
    ScheduleLessonExecutor,
    RecordPracticeExecutor,
    SendEmailExecutor,
    SendSMSExecutor,
    get_executor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_state():
    # Ensure shared class-level stores are cleared between tests
    BookViewingExecutor.BOOKINGS.clear()
    CreateOrUpdateCVExecutor.USER_CVS.clear()
    ScheduleLessonExecutor.LESSONS.clear()
    RecordPracticeExecutor.PRACTICE_LOG.clear()
    SendEmailExecutor.EMAIL_LOG.clear()
    SendSMSExecutor.SMS_LOG.clear()
    yield


# ---------------------------------------------------------------------------
# SearchListingsExecutor
# ---------------------------------------------------------------------------

class TestSearchListings:
    def test_validate_requires_location(self):
        ex = SearchListingsExecutor("sess1")
        valid, errs = ex.validate({})
        assert not valid
        assert "location is required" in errs

    def test_validate_price_checks(self):
        ex = SearchListingsExecutor("sess1")
        valid, errs = ex.validate({"location": "Oslo", "price_min": -10})
        assert not valid
        assert any("price_min" in e for e in errs)

    def test_execute_filters_and_keywords(self):
        ex = SearchListingsExecutor("sess1")
        res = ex.execute({"location": "Oslo", "keywords": "renovated"})
        assert res["status"] == "success"
        assert res["data"]["count"] >= 1
        # When beds_min unrealistic -> no results
        res2 = ex.execute({"location": "Oslo", "beds_min": 100})
        assert res2["data"]["count"] == 0


# ---------------------------------------------------------------------------
# GetListingDetailsExecutor
# ---------------------------------------------------------------------------

class TestGetListingDetails:
    def test_validate_missing_listing_id(self):
        ex = GetListingDetailsExecutor("s1")
        valid, errs = ex.validate({})
        assert not valid
        assert "listing_id is required" in errs

    def test_execute_not_found(self):
        ex = GetListingDetailsExecutor("s1")
        out = ex.execute({"listing_id": "nonexistent"})
        assert out["status"] == "error"
        assert "not found" in out["error_message"].lower()


# ---------------------------------------------------------------------------
# BookViewingExecutor
# ---------------------------------------------------------------------------

class TestBookViewing:
    def test_validate_preferred_windows_type(self):
        ex = BookViewingExecutor("sess1")
        valid, errs = ex.validate({"listing_id": "lst", "preferred_windows": "notalist"})
        assert not valid
        assert "preferred_windows must be a list" in str(errs)

    def test_execute_creates_pending_and_confirms(self):
        ex = BookViewingExecutor("sess1")
        out = ex.execute({"listing_id": "lst_1", "preferred_windows": ["2026-02-15"], "user_name": "A"})
        assert out["status"] == "success"
        booking_id = out["data"]["booking_id"]
        assert booking_id in BookViewingExecutor.BOOKINGS

        # Confirm booking
        ok, msg = BookViewingExecutor.confirm_booking(booking_id, "2026-02-15 14:00")
        assert ok
        assert "confirmed" in msg

        # Confirm again should fail
        ok2, msg2 = BookViewingExecutor.confirm_booking(booking_id, "2026-02-15 14:00")
        assert not ok2
        assert "already" in msg2


# ---------------------------------------------------------------------------
# CreateOrUpdateCVExecutor
# ---------------------------------------------------------------------------

class TestCreateOrUpdateCV:
    def test_validate_requires_full_name(self):
        ex = CreateOrUpdateCVExecutor("sess1")
        ok, errs = ex.validate({})
        assert not ok
        assert "full_name is required" in errs

    def test_execute_creates_cv_and_preview(self):
        ex = CreateOrUpdateCVExecutor("user123")
        out = ex.execute({"full_name": "Alice", "sections": {"experience": ["Dev"]}})
        assert out["status"] == "success"
        data = out["data"]
        assert "cv_id" in data
        assert "preview" in data
        assert data["full_name"] == "Alice"


# ---------------------------------------------------------------------------
# ScheduleLessonExecutor
# ---------------------------------------------------------------------------

class TestScheduleLesson:
    def test_validate_missing_and_invalid_duration(self):
        ex = ScheduleLessonExecutor("sess1")
        ok, errs = ex.validate({})
        assert not ok
        assert "tutor_id is required" in errs
        assert "duration_minutes is required" in errs

        ok2, errs2 = ex.validate({"tutor_id": "t1", "scheduled_time": "tomorrow", "duration_minutes": 0})
        assert not ok2
        assert "duration_minutes must be positive integer" in errs2

    def test_execute_creates_lesson(self):
        ex = ScheduleLessonExecutor("student1")
        out = ex.execute({"tutor_id": "t1", "scheduled_time": "2026-02-15T10:00:00", "duration_minutes": 30})
        assert out["status"] == "success"
        assert "lesson_id" in out["data"]


# ---------------------------------------------------------------------------
# RecordPracticeExecutor
# ---------------------------------------------------------------------------

class TestRecordPractice:
    def test_validate_missing_fields(self):
        ex = RecordPracticeExecutor("sess1")
        ok, errs = ex.validate({})
        assert not ok
        assert "duration_minutes is required" in errs

    def test_execute_accumulates_stats(self):
        ex = RecordPracticeExecutor("user_abc")
        out1 = ex.execute({"duration_minutes": 20, "activity": "speaking"})
        assert out1["status"] == "success"
        out2 = ex.execute({"duration_minutes": 15, "activity": "writing"})
        assert out2["data"]["session_total_minutes"] == 35
        assert out2["data"]["sessions_count"] == 2


# ---------------------------------------------------------------------------
# SendEmailExecutor
# ---------------------------------------------------------------------------

class TestSendEmail:
    def test_validate_email_format_and_required(self):
        ex = SendEmailExecutor("sess1")
        ok, errs = ex.validate({"to": "invalid", "subject": "s", "body": "b"})
        assert not ok
        assert any("must be valid email" in e for e in errs)

    def test_execute_logs_email(self):
        ex = SendEmailExecutor("sess_user")
        out = ex.execute({"to": "u@example.com", "subject": "Hi", "body": "Hello"})
        assert out["status"] == "success"
        assert "email_id" in out["data"]
        # email should be in log
        assert "sess_user" in SendEmailExecutor.EMAIL_LOG
        assert SendEmailExecutor.EMAIL_LOG["sess_user"][0]["status"] == "sent"


# ---------------------------------------------------------------------------
# SendSMSExecutor
# ---------------------------------------------------------------------------

class TestSendSMS:
    def test_validate_message_limit(self):
        ex = SendSMSExecutor("sess1")
        ok, errs = ex.validate({"phone": "+471234", "message": "x" * 161})
        assert not ok
        assert any("160 chars" in e for e in errs)

    def test_execute_logs_sms(self):
        ex = SendSMSExecutor("sess_user")
        out = ex.execute({"phone": "+4712345678", "message": "Hello"})
        assert out["status"] == "success"
        assert "sms_id" in out["data"]
        assert "sess_user" in SendSMSExecutor.SMS_LOG


# ---------------------------------------------------------------------------
# get_executor mapping
# ---------------------------------------------------------------------------

def test_get_executor_mapping():
    ex = get_executor("search_listings", "s1")
    assert isinstance(ex, SearchListingsExecutor)

    ex_none = get_executor("unknown_action", "s1")
    assert ex_none is None

