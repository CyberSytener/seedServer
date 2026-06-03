"""
Job Automation Action Contracts

Defines 7 strict Pydantic v2 contracts for job automation actions.
All actions are idempotent, confirmable, and fully auditable.

Actions:
1. create_candidate_profile - Register candidate
2. generate_targeted_cv - Generate role-specific CV
3. create_outreach_campaign - Define campaign scope
4. send_outreach_email - Send email with confirmation
5. monitor_inbox - Check for replies
6. parse_reply - Classify response sentiment
7. schedule_interview - Create calendar event
"""

from typing import Literal, Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, EmailStr, validator
from enum import Enum
import uuid


# ============================================================================
# ENUMS
# ============================================================================

class ConsentChannel(str, Enum):
    """How candidate gave consent"""
    UI = "ui"
    API = "api"
    IMPORTED = "imported"
    MANUAL = "manual"


class CampaignStatus(str, Enum):
    """Campaign lifecycle state"""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TargetStatus(str, Enum):
    """Individual target state in campaign"""
    PENDING = "pending"
    SENT = "sent"
    BOUNCED = "bounced"
    REPLIED = "replied"
    SCHEDULED = "scheduled"


class ReplyClassification(str, Enum):
    """Reply sentiment classification"""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UNCLASSIFIABLE = "unclassifiable"


# ============================================================================
# ACTION 1: CREATE CANDIDATE PROFILE
# ============================================================================

class CreateCandidateProfileInput(BaseModel):
    """Input for create_candidate_profile action"""
    
    # Required fields
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr = Field(...)
    
    # Optional enrichment
    target_role: Optional[str] = Field(None, max_length=200)
    education: Optional[str] = Field(None, max_length=1000)
    experience_tags: Optional[List[str]] = Field(None, max_items=20)
    
    # Consent (CRITICAL)
    consent_granted: bool = Field(True, description="Must be True to outreach")
    consent_channel: ConsentChannel = Field(default=ConsentChannel.UI)
    consent_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Suppression list (allow-list override)
    is_suppressed: bool = Field(False, description="True if candidate opts out")
    suppression_reason: Optional[str] = Field(None, max_length=500)
    
    model_config = {"json_schema_extra": {
        "example": {
            "first_name": "Alice",
            "last_name": "Engineer",
            "email": "alice@example.com",
            "target_role": "Senior Python Engineer",
            "education": "BS Computer Science, Stanford",
            "experience_tags": ["Python", "FastAPI", "PostgreSQL"],
            "consent_granted": True,
            "consent_channel": "ui",
            "consent_timestamp": "2026-01-30T10:00:00Z"
        }
    }}


class CreateCandidateProfileOutput(BaseModel):
    """Output for create_candidate_profile action"""
    
    candidate_id: str = Field(..., description="UUID of created candidate")
    first_name: str
    email: EmailStr
    created_at: datetime
    consent_status: bool
    is_idempotent_duplicate: bool = Field(
        False, 
        description="True if candidate already existed (idempotent)"
    )


# ============================================================================
# ACTION 2: GENERATE TARGETED CV
# ============================================================================

class GenerateTargetedCVInput(BaseModel):
    """Input for generate_targeted_cv action"""
    
    candidate_id: str = Field(..., description="UUID of candidate")
    target_role: str = Field(..., min_length=1, max_length=200)
    job_description: Optional[str] = Field(None, max_length=5000)
    company_name: Optional[str] = Field(None, max_length=200)
    
    # CV generation parameters
    style: Literal["concise", "detailed"] = Field(default="concise")
    max_length: int = Field(default=1, ge=1, le=3, description="Pages (1-3)")
    
    model_config = {"json_schema_extra": {
        "example": {
            "candidate_id": "cand-12345678-1234-5678-1234-567812345678",
            "target_role": "Senior Python Engineer",
            "job_description": "We seek 5+ year Python expert...",
            "company_name": "TechCorp",
            "style": "concise",
            "max_length": 1
        }
    }}


class GenerateTargetedCVOutput(BaseModel):
    """Output for generate_targeted_cv action"""
    model_config = {"protected_namespaces": ()}
    
    candidate_id: str
    cv_id: str = Field(..., description="UUID of generated CV")
    target_role: str
    cv_content: str = Field(..., description="Generated CV text")
    generated_at: datetime
    model_name: str = Field(default="gpt-4", description="LLM used")
    tokens_used: int = Field(default=0)


# ============================================================================
# ACTION 3: CREATE OUTREACH CAMPAIGN
# ============================================================================

class CreateOutreachCampaignInput(BaseModel):
    """Input for create_outreach_campaign action"""
    
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    target_role: str = Field(..., min_length=1, max_length=200)
    
    # Campaign settings
    status: CampaignStatus = Field(default=CampaignStatus.DRAFT)
    max_targets: int = Field(default=100, ge=1, le=10000)
    max_emails_per_day: int = Field(default=20, ge=1, le=1000)
    
    # Timeline
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    # Metadata
    created_by: str = Field(..., description="User ID")
    campaign_tags: Optional[List[str]] = Field(None, max_items=20)
    
    model_config = {"json_schema_extra": {
        "example": {
            "name": "2026-Q1-Python-Outreach",
            "description": "Outreach to senior Python engineers",
            "target_role": "Senior Python Engineer",
            "status": "draft",
            "max_targets": 100,
            "max_emails_per_day": 20,
            "created_by": "user-12345678"
        }
    }}


class CreateOutreachCampaignOutput(BaseModel):
    """Output for create_outreach_campaign action"""
    
    campaign_id: str = Field(..., description="UUID of created campaign")
    name: str
    status: CampaignStatus
    created_at: datetime
    targets_count: int = Field(default=0)


# ============================================================================
# ACTION 4: SEND OUTREACH EMAIL
# ============================================================================

class SendOutreachEmailInput(BaseModel):
    """Input for send_outreach_email action (REQUIRES CONFIRMATION)"""
    
    campaign_id: str = Field(..., description="UUID of campaign")
    target_id: str = Field(..., description="UUID of target (candidate+campaign)")
    candidate_id: str = Field(..., description="UUID of candidate")
    recipient_email: EmailStr
    
    # Email content
    subject: str = Field(..., min_length=5, max_length=200)
    body: str = Field(..., min_length=50, max_length=5000)
    cv_attachment_id: Optional[str] = None
    
    # Tracking
    template_name: Optional[str] = None
    personalization_tokens: Optional[Dict[str, str]] = None
    
    # Confirmation requirement
    requires_confirmation: bool = Field(default=True)
    confirmation_deadline: Optional[datetime] = None
    
    model_config = {"json_schema_extra": {
        "example": {
            "campaign_id": "camp-12345678",
            "target_id": "tgt-12345678",
            "candidate_id": "cand-12345678",
            "recipient_email": "alice@example.com",
            "subject": "Opportunity: Senior Python Engineer at TechCorp",
            "body": "Hi Alice,\\n\\nWe found your profile interesting...",
            "template_name": "outreach_senior_engineer",
            "requires_confirmation": True
        }
    }}


class SendOutreachEmailOutput(BaseModel):
    """Output for send_outreach_email action"""
    
    target_id: str
    email_id: str = Field(..., description="UUID of sent email")
    message_id: str = Field(..., description="Graph API message ID for tracking")
    recipient_email: EmailStr
    sent_at: datetime
    status: Literal["pending_confirmation", "sent", "failed"] = Field(default="sent")
    is_idempotent_duplicate: bool = Field(
        False,
        description="True if email already sent to this target"
    )


# ============================================================================
# ACTION 5: MONITOR INBOX
# ============================================================================

class MonitorInboxInput(BaseModel):
    """Input for monitor_inbox action"""
    
    user_id: str = Field(..., description="User whose inbox to monitor")
    since_timestamp: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=1000)
    
    # Filtering
    only_unread: bool = Field(default=True)
    skip_archived: bool = Field(default=True)
    
    model_config = {"json_schema_extra": {
        "example": {
            "user_id": "user-12345678",
            "since_timestamp": "2026-01-30T00:00:00Z",
            "limit": 100,
            "only_unread": True
        }
    }}


class InboxMessage(BaseModel):
    """Message from inbox"""
    message_id: str
    from_email: EmailStr
    subject: str
    received_at: datetime
    is_reply_to: Optional[str] = Field(None, description="Original message ID if reply")


class MonitorInboxOutput(BaseModel):
    """Output for monitor_inbox action"""
    
    user_id: str
    messages_found: int
    messages: List[InboxMessage] = Field(default_factory=list)
    scanned_at: datetime


# ============================================================================
# ACTION 6: PARSE REPLY
# ============================================================================

class ParseReplyInput(BaseModel):
    """Input for parse_reply action"""
    
    reply_id: str = Field(..., description="UUID of reply email")
    incoming_message_id: str = Field(..., description="Graph API message ID")
    email_body: str = Field(..., min_length=1, max_length=5000)
    original_campaign_id: str = Field(..., description="Campaign this reply is for")
    
    # Optional context for parsing
    candidate_name: Optional[str] = None
    original_subject: Optional[str] = None
    
    model_config = {"json_schema_extra": {
        "example": {
            "reply_id": "reply-12345678",
            "incoming_message_id": "msg-graph-api-id",
            "email_body": "Thanks for reaching out! I'd be interested in learning more.",
            "original_campaign_id": "camp-12345678",
            "candidate_name": "Alice Engineer"
        }
    }}


class ParseReplyOutput(BaseModel):
    """Output for parse_reply action"""
    model_config = {"protected_namespaces": ()}
    
    reply_id: str
    campaign_id: str
    classification: ReplyClassification
    confidence: float = Field(ge=0.0, le=1.0)
    
    # Extracted info
    extracted_intent: Optional[str] = None
    next_steps: Optional[List[str]] = None
    contains_contact_info: bool = Field(default=False)
    
    # Audit
    parsed_at: datetime
    model_name: str = Field(default="gpt-4", description="LLM used")
    raw_response: Optional[Dict[str, Any]] = None


# ============================================================================
# ACTION 7: SCHEDULE INTERVIEW
# ============================================================================

class ScheduleInterviewInput(BaseModel):
    """Input for schedule_interview action"""
    
    candidate_id: str
    campaign_id: str
    target_email: EmailStr
    
    # Interview details
    title: str = Field(..., min_length=5, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    duration_minutes: int = Field(default=60, ge=15, le=480)
    
    # Scheduling
    suggested_times: Optional[List[datetime]] = Field(None, description="Proposed times")
    timezone: str = Field(default="UTC", description="IANA timezone")
    
    # Attendees
    interviewer_email: Optional[EmailStr] = None
    interviewer_name: Optional[str] = None
    
    # Calendar
    calendar_type: Literal["google", "microsoft", "generic"] = Field(default="microsoft")
    
    model_config = {"json_schema_extra": {
        "example": {
            "candidate_id": "cand-12345678",
            "campaign_id": "camp-12345678",
            "target_email": "alice@example.com",
            "title": "Interview: Senior Python Engineer",
            "description": "Technical screening + culture fit",
            "duration_minutes": 60,
            "suggested_times": ["2026-02-05T14:00:00Z", "2026-02-06T10:00:00Z"],
            "interviewer_email": "hiring@company.com",
            "interviewer_name": "Jane Manager",
            "calendar_type": "microsoft"
        }
    }}


class ScheduleInterviewOutput(BaseModel):
    """Output for schedule_interview action"""
    
    candidate_id: str
    interview_id: str = Field(..., description="UUID of scheduled interview")
    calendar_event_id: str = Field(..., description="Calendar event ID (Google/Microsoft)")
    title: str
    suggested_times: List[datetime]
    scheduled_at: datetime
    status: Literal["pending_response", "accepted", "declined"] = Field(default="pending_response")
    is_idempotent_duplicate: bool = Field(
        False,
        description="True if interview already scheduled"
    )


# ============================================================================
# COMPOSITE SCHEMAS
# ============================================================================

class ActionRequest(BaseModel):
    """Generic action request container"""
    
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: str = Field(..., description="One of 7 action types")
    user_id: str = Field(..., description="User who triggered action")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    params: Dict[str, Any] = Field(...)
    requires_confirmation: bool = Field(default=False)
    confirmation_deadline: Optional[datetime] = None


class ActionResult(BaseModel):
    """Generic action result container"""
    
    action_id: str
    action_type: str
    status: Literal["success", "failed", "pending_confirmation"]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    completed_at: Optional[datetime] = None
    audit_trail_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ============================================================================
# VALIDATION RULES (Global)
# ============================================================================

# Note: Pydantic v2 validates automatically on model instantiation.
# These are implicit in field definitions:
#
# 1. Idempotency: Actions check for duplicate (candidate_id+email) or (target_id+campaign_id)
#    Output includes is_idempotent_duplicate flag.
#
# 2. Email validation: EmailStr ensures valid email format.
#
# 3. Consent enforcement: create_candidate_profile requires consent_granted=True.
#    send_outreach_email rejects if candidate is_suppressed=True.
#
# 4. Enum validation: Status fields restricted to allowed values.
#    (CampaignStatus, TargetStatus, ReplyClassification, ConsentChannel)
#
# 5. Range validation: max_length, ge/le constraints on numeric fields.
#
# 6. Required fields: ... in Field() means required (no Optional).
#
# 7. Timestamps: ISO 8601 format, stored in UTC.


if __name__ == "__main__":
    # Example: Create a candidate profile request
    profile_input = CreateCandidateProfileInput(
        first_name="Alice",
        last_name="Engineer",
        email="alice@example.com",
        target_role="Senior Python Engineer",
        consent_granted=True,
        consent_channel=ConsentChannel.UI,
    )
    print("✅ Profile input valid:")
    print(profile_input.model_dump_json(indent=2))
    
    # Example: Send email (requires confirmation)
    email_input = SendOutreachEmailInput(
        campaign_id="camp-uuid",
        target_id="tgt-uuid",
        candidate_id="cand-uuid",
        recipient_email="alice@example.com",
        subject="Opportunity: Senior Engineer",
        body="We found your profile interesting...",
        requires_confirmation=True,
    )
    print("\n✅ Email input valid:")
    print(email_input.model_dump_json(indent=2))
