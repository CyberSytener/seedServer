"""
Job Automation Database Migrations

5 core tables for job automation system:
1. candidates - Candidate profiles
2. outreach_campaigns - Campaign definitions
3. outreach_targets - Individual target per campaign
4. email_events - Email send/delivery tracking
5. reply_events - Reply parsing & classification

All tables include:
- Audit trail: created_at, updated_at, created_by
- State tracking: status enums
- Foreign keys with CASCADE/RESTRICT as appropriate
- Indexes on frequently queried columns
- Constraints: NOT NULL, UNIQUE where needed

Usage:
    python -m alembic upgrade head
    python init_db.py

Structure:
    - DDL: SQL schema definitions
    - Relationships: Foreign keys and constraints
    - Indexes: Query optimization
    - Archive: Cleanup functions for old data
"""

from datetime import datetime
from enum import Enum
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    Float,
    Enum as SQLEnum,
    ForeignKey,
    UniqueConstraint,
    Index,
    MetaData,
    Table,
    JSON,
    event,
)
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import Optional, List

Base = declarative_base()


# ============================================================================
# ENUMS
# ============================================================================

class ConsentChannelEnum(str, Enum):
    """How candidate gave consent"""
    UI = "ui"
    API = "api"
    IMPORTED = "imported"
    MANUAL = "manual"


class CampaignStatusEnum(str, Enum):
    """Campaign lifecycle"""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TargetStatusEnum(str, Enum):
    """Target state in campaign"""
    PENDING = "pending"
    SENT = "sent"
    BOUNCED = "bounced"
    REPLIED = "replied"
    SCHEDULED = "scheduled"


class ReplyClassificationEnum(str, Enum):
    """Reply sentiment"""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UNCLASSIFIABLE = "unclassifiable"


# ============================================================================
# TABLE 1: CANDIDATES
# ============================================================================

class Candidate(Base):
    """
    Candidate profile table
    
    Tracks:
    - Personal info (name, email)
    - Target role
    - Education/experience tags
    - Consent status and channel
    - Suppression status (opt-out)
    """
    
    __tablename__ = "candidates"
    
    # Primary key
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        doc="UUID",
    )
    
    # Personal info
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    
    # Target info
    target_role: Mapped[Optional[str]] = mapped_column(String(200))
    education: Mapped[Optional[str]] = mapped_column(Text)
    experience_tags: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    
    # Consent tracking
    consent_granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consent_channel: Mapped[str] = mapped_column(
        SQLEnum(ConsentChannelEnum),
        default=ConsentChannelEnum.UI,
        nullable=False,
    )
    consent_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    
    # Suppression
    is_suppressed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suppression_reason: Mapped[Optional[str]] = mapped_column(Text)
    suppression_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    
    # Relationships
    outreach_targets: Mapped[List["OutreachTarget"]] = relationship(
        "OutreachTarget",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    email_events: Mapped[List["EmailEvent"]] = relationship(
        "EmailEvent",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    reply_events: Mapped[List["ReplyEvent"]] = relationship(
        "ReplyEvent",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("idx_candidate_email_suppressed", "email", "is_suppressed"),
        Index("idx_candidate_consent", "consent_granted", "is_suppressed"),
        Index("idx_candidate_created_at", "created_at"),
    )


# ============================================================================
# TABLE 2: OUTREACH CAMPAIGNS
# ============================================================================

class OutreachCampaign(Base):
    """
    Campaign definition table
    
    Tracks:
    - Campaign metadata (name, description, goal)
    - Status (draft/active/paused/completed/archived)
    - Scope (max targets, emails per day)
    - Timeline
    """
    
    __tablename__ = "outreach_campaigns"
    
    # Primary key
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        doc="UUID",
    )
    
    # Campaign info
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    target_role: Mapped[str] = mapped_column(String(200), nullable=False)
    
    # Status
    status: Mapped[str] = mapped_column(
        SQLEnum(CampaignStatusEnum),
        default=CampaignStatusEnum.DRAFT,
        nullable=False,
        index=True,
    )
    
    # Scope
    max_targets: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_emails_per_day: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    
    # Timeline
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Consent tracking (when users approved this campaign)
    consent_granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Metadata
    campaign_tags: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    
    # Statistics
    targets_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    replied_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Relationships
    outreach_targets: Mapped[List["OutreachTarget"]] = relationship(
        "OutreachTarget",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    email_events: Mapped[List["EmailEvent"]] = relationship(
        "EmailEvent",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("idx_campaign_status_created", "status", "created_at"),
        Index("idx_campaign_created_by", "created_by"),
    )


# ============================================================================
# TABLE 3: OUTREACH TARGETS
# ============================================================================

class OutreachTarget(Base):
    """
    Individual target in a campaign
    
    Tracks:
    - Which candidate in which campaign
    - Current state (pending/sent/replied/scheduled)
    - Timestamps for each milestone
    - Message ID mapping for tracking
    """
    
    __tablename__ = "outreach_targets"
    
    # Primary key
    target_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        doc="UUID",
    )
    
    # Foreign keys
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("outreach_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("candidates.candidate_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Target info
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Status
    status: Mapped[str] = mapped_column(
        SQLEnum(TargetStatusEnum),
        default=TargetStatusEnum.PENDING,
        nullable=False,
        index=True,
    )
    
    # Timeline
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Message tracking
    last_message_id: Mapped[Optional[str]] = mapped_column(String(255))  # Graph API ID
    last_email_id: Mapped[Optional[str]] = mapped_column(String(36))  # Our email UUID
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    # Relationships
    campaign: Mapped["OutreachCampaign"] = relationship(
        "OutreachCampaign",
        back_populates="outreach_targets",
    )
    candidate: Mapped["Candidate"] = relationship(
        "Candidate",
        back_populates="outreach_targets",
    )
    email_events: Mapped[List["EmailEvent"]] = relationship(
        "EmailEvent",
        back_populates="outreach_target",
        cascade="all, delete-orphan",
    )
    reply_events: Mapped[List["ReplyEvent"]] = relationship(
        "ReplyEvent",
        back_populates="outreach_target",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        UniqueConstraint("campaign_id", "candidate_id", name="ux_campaign_candidate"),
        Index("idx_target_campaign_status", "campaign_id", "status"),
        Index("idx_target_replied_at", "replied_at"),
    )


# ============================================================================
# TABLE 4: EMAIL EVENTS
# ============================================================================

class EmailEvent(Base):
    """
    Email send/delivery tracking
    
    Tracks:
    - Email send timestamp
    - Delivery events (opened, clicked, bounced)
    - Message ID mapping for inbox monitoring
    """
    
    __tablename__ = "email_events"
    
    # Primary key
    email_event_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        doc="UUID",
    )
    
    # Foreign keys
    target_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("outreach_targets.target_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("outreach_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("candidates.candidate_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Message mapping
    email_id: Mapped[str] = mapped_column(String(36), nullable=False)  # Our UUID
    outreach_email_id: Mapped[Optional[str]] = mapped_column(String(255))  # Graph API ID
    
    # Send event
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    sent_from: Mapped[str] = mapped_column(String(255), nullable=False)
    sent_to: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    
    # Delivery events
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    clicked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    bounced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    bounce_reason: Mapped[Optional[str]] = mapped_column(Text)
    
    # Metadata
    template_name: Mapped[Optional[str]] = mapped_column(String(100))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    outreach_target: Mapped["OutreachTarget"] = relationship(
        "OutreachTarget",
        back_populates="email_events",
    )
    campaign: Mapped["OutreachCampaign"] = relationship(
        "OutreachCampaign",
        back_populates="email_events",
    )
    candidate: Mapped["Candidate"] = relationship(
        "Candidate",
        back_populates="email_events",
    )
    
    __table_args__ = (
        UniqueConstraint("email_id", name="ux_email_id"),
        UniqueConstraint("outreach_email_id", name="ux_outreach_email_id"),
        Index("idx_email_sent_at", "sent_at"),
        Index("idx_email_bounced_at", "bounced_at"),
        Index("idx_email_campaign_sent", "campaign_id", "sent_at"),
    )


# ============================================================================
# TABLE 5: REPLY EVENTS
# ============================================================================

class ReplyEvent(Base):
    """
    Reply detection and parsing
    
    Tracks:
    - Reply received timestamp
    - Classification (positive/neutral/negative)
    - Extracted intent and next steps
    - Contact info detection
    """
    
    __tablename__ = "reply_events"
    
    # Primary key
    reply_event_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        doc="UUID",
    )
    
    # Foreign keys
    target_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("outreach_targets.target_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("candidates.candidate_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Message mapping
    reply_id: Mapped[str] = mapped_column(String(36), nullable=False)  # Our UUID
    incoming_email_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)  # Graph API ID
    
    # Receipt
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    
    # Classification
    classification: Mapped[str] = mapped_column(
        SQLEnum(ReplyClassificationEnum),
        default=ReplyClassificationEnum.UNCLASSIFIABLE,
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Extracted info
    extracted_intent: Mapped[Optional[str]] = mapped_column(Text)
    next_steps: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    contains_contact_info: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Original message for audit
    original_message: Mapped[Optional[str]] = mapped_column(Text)
    
    # Parsing metadata
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    parser_model: Mapped[str] = mapped_column(String(100), default="gpt-4")
    parser_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    
    # Audit trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        nullable=False,
    )
    
    # Relationships
    outreach_target: Mapped["OutreachTarget"] = relationship(
        "OutreachTarget",
        back_populates="reply_events",
    )
    candidate: Mapped["Candidate"] = relationship(
        "Candidate",
        back_populates="reply_events",
    )
    
    __table_args__ = (
        Index("idx_reply_received_at", "received_at"),
        Index("idx_reply_classification", "classification"),
        Index("idx_reply_candidate_received", "candidate_id", "received_at"),
    )


# ============================================================================
# MIGRATION FUNCTIONS
# ============================================================================

def create_all_tables(engine):
    """
    Create all tables in database
    
    Usage:
        engine = create_engine("postgresql://user:pass@localhost/job_automation")
        create_all_tables(engine)
    """
    Base.metadata.create_all(engine)
    print("✅ All tables created successfully")


def drop_all_tables(engine):
    """
    Drop all tables (DESTRUCTIVE - use with caution)
    
    Usage:
        engine = create_engine("postgresql://user:pass@localhost/job_automation")
        drop_all_tables(engine)
    """
    Base.metadata.drop_all(engine)
    print("⚠️  All tables dropped")


def archive_old_data(engine, days_before_archive: int = 90):
    """
    Archive email and reply events older than X days
    
    Usage:
        archive_old_data(engine, days_before_archive=90)
    """
    from datetime import datetime, timedelta, timezone
    
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_before_archive)
    
    # This would be expanded in production to:
    # 1. Export to archive table
    # 2. Delete from main table
    # 3. Log archival event
    
    print(f"⚠️  Archive date: {cutoff_date}")
    print("   Note: Implement archival strategy based on retention policy")


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

if __name__ == "__main__":
    # Example: Create tables
    engine = create_engine("sqlite:///job_automation_test.db")
    create_all_tables(engine)
    
    # Print schema summary
    print("\n📊 Database Schema Summary:")
    print("=" * 60)
    for table_name, table in Base.metadata.tables.items():
        print(f"\n📋 {table_name}")
        print(f"   Columns: {len(table.columns)}")
        for col in table.columns:
            print(f"     - {col.name}: {col.type}")
    
    print("\n✅ Schema migration ready for production")
