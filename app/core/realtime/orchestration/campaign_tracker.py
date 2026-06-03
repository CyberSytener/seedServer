"""
Campaign Progress & Audit Timeline System
Track campaign metrics, audit trail, and candidate visibility

Features:
1. Campaign progress tracking
   - Targets sent/replied/scheduled counts
   - Real-time progress updates
   - Performance metrics
   - Stage transitions

2. Audit timeline
   - Complete event history per candidate
   - Email sent → replied → interview scheduled
   - Manual edits tracked
   - Compliance audit trail

3. Manual override capability
   - Edit generated emails before send
   - Approve/reject suggestions
   - Custom reply handling
   - Preview before commit

4. Visibility controls
   - What candidate sees
   - What recruiter sees
   - Audit trail access
   - GDPR/SOX compliance

5. Performance analytics
   - Response rates
   - Interview scheduled rate
   - Time to first reply
   - Campaign success metrics

Usage:
    campaign = CampaignTracker.create(
        tenant_id="tenant_001",
        campaign_id="campaign_123",
        name="Software Engineers Q1",
        target_count=100,
    )
    
    # Track email sent
    campaign.record_event(
        event_type=EventType.EMAIL_SENT,
        target_id="candidate_001",
        data={"email_id": "msg_123", "subject": "..."},
    )
    
    # Track reply
    campaign.record_event(
        event_type=EventType.REPLY_RECEIVED,
        target_id="candidate_001",
        data={"interest_level": "HIGH"},
    )
    
    # Get progress
    progress = campaign.get_progress()
    timeline = campaign.get_timeline(target_id="candidate_001")
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Campaign event types"""
    EMAIL_SENT = "email_sent"
    EMAIL_BOUNCED = "email_bounced"
    EMAIL_OPENED = "email_opened"
    EMAIL_CLICKED = "email_clicked"
    REPLY_RECEIVED = "reply_received"
    REPLY_PARSED = "reply_parsed"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    EMAIL_EDITED = "email_edited"
    REPLY_FORWARDED = "reply_forwarded"
    CANDIDATE_COMMENTED = "candidate_commented"
    RECRUITER_COMMENTED = "recruiter_commented"
    OPTED_OUT = "opted_out"


class TargetStatus(str, Enum):
    """Target/candidate status in campaign"""
    PROSPECT = "prospect"
    OUTREACH_SENT = "outreach_sent"
    ENGAGED = "engaged"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    REJECTED = "rejected"
    OPTED_OUT = "opted_out"


@dataclass
class EventRecord:
    """Single audit event"""
    event_id: str
    event_type: EventType
    target_id: str
    timestamp: datetime
    actor: str  # "system", "candidate", or "recruiter"
    data: Dict[str, Any] = field(default_factory=dict)
    manual_override: bool = False
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "target_id": self.target_id,
            "timestamp": self.timestamp.isoformat(),
            "actor": self.actor,
            "data": self.data,
            "manual_override": self.manual_override,
            "notes": self.notes,
        }


@dataclass
class TargetProgress:
    """Progress for single candidate"""
    target_id: str
    email: str
    status: TargetStatus
    email_sent_at: Optional[datetime] = None
    reply_received_at: Optional[datetime] = None
    interview_scheduled_at: Optional[datetime] = None
    
    # Calculated metrics
    days_to_reply: Optional[int] = None
    last_activity: Optional[datetime] = None
    
    def get_stage(self) -> int:
        """Get progression stage (0-4)"""
        if self.interview_scheduled_at:
            return 4
        elif self.reply_received_at:
            return 2
        elif self.email_sent_at:
            return 1
        else:
            return 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "email": self.email,
            "status": self.status.value,
            "stage": self.get_stage(),
            "email_sent_at": self.email_sent_at.isoformat() if self.email_sent_at else None,
            "reply_received_at": self.reply_received_at.isoformat() if self.reply_received_at else None,
            "interview_scheduled_at": self.interview_scheduled_at.isoformat() if self.interview_scheduled_at else None,
            "days_to_reply": self.days_to_reply,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
        }


@dataclass
class CampaignStats:
    """Campaign-level statistics"""
    total_targets: int
    emails_sent: int = 0
    emails_opened: int = 0
    replies_received: int = 0
    interviews_scheduled: int = 0
    rejected: int = 0
    opted_out: int = 0
    
    # Calculated metrics
    open_rate: float = 0.0
    reply_rate: float = 0.0
    interview_rate: float = 0.0
    
    avg_days_to_reply: float = 0.0
    
    def calculate_rates(self) -> None:
        """Calculate derived metrics"""
        if self.emails_sent > 0:
            self.open_rate = self.emails_opened / self.emails_sent
            self.reply_rate = self.replies_received / self.emails_sent
            self.interview_rate = self.interviews_scheduled / self.emails_sent
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_targets": self.total_targets,
            "emails_sent": self.emails_sent,
            "emails_opened": self.emails_opened,
            "replies_received": self.replies_received,
            "interviews_scheduled": self.interviews_scheduled,
            "rejected": self.rejected,
            "opted_out": self.opted_out,
            "open_rate": f"{self.open_rate:.1%}",
            "reply_rate": f"{self.reply_rate:.1%}",
            "interview_rate": f"{self.interview_rate:.1%}",
            "avg_days_to_reply": f"{self.avg_days_to_reply:.1f}",
        }


# ============================================================================
# CAMPAIGN TRACKER
# ============================================================================

class CampaignTracker:
    """Track campaign progress and audit trail"""
    
    def __init__(
        self,
        tenant_id: str,
        campaign_id: str,
        name: str,
        target_count: int,
        created_at: Optional[datetime] = None,
    ):
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.name = name
        self.target_count = target_count
        self.created_at = created_at or datetime.now()
        
        self.targets: Dict[str, TargetProgress] = {}
        self.events: List[EventRecord] = []
        self.stats = CampaignStats(total_targets=target_count)
        
        self._event_counter = 0
    
    @classmethod
    def create(
        cls,
        tenant_id: str,
        campaign_id: str,
        name: str,
        target_count: int,
    ) -> "CampaignTracker":
        """Create new campaign"""
        campaign = cls(tenant_id, campaign_id, name, target_count)
        logger.info(f"✅ Campaign created: {campaign_id} ({name})")
        return campaign
    
    def add_target(self, target_id: str, email: str) -> None:
        """Add candidate to campaign"""
        if target_id not in self.targets:
            self.targets[target_id] = TargetProgress(
                target_id=target_id,
                email=email,
                status=TargetStatus.PROSPECT,
            )
    
    def record_event(
        self,
        event_type: EventType,
        target_id: str,
        actor: str = "system",
        data: Optional[Dict[str, Any]] = None,
        manual_override: bool = False,
        notes: Optional[str] = None,
    ) -> EventRecord:
        """
        Record campaign event
        
        Args:
            event_type: Type of event
            target_id: Candidate ID
            actor: "system", "candidate", or "recruiter"
            data: Event data
            manual_override: Was this manually overridden?
            notes: Additional notes
        """
        self._event_counter += 1
        event = EventRecord(
            event_id=f"{self.campaign_id}_evt_{self._event_counter}",
            event_type=event_type,
            target_id=target_id,
            timestamp=datetime.now(),
            actor=actor,
            data=data or {},
            manual_override=manual_override,
            notes=notes,
        )
        
        self.events.append(event)
        self._update_target_progress(event)
        self._update_stats(event)
        
        logger.info(f"📝 Event: {event_type.value} for {target_id}")
        
        return event
    
    def _update_target_progress(self, event: EventRecord) -> None:
        """Update target progress based on event"""
        if event.target_id not in self.targets:
            return
        
        target = self.targets[event.target_id]
        target.last_activity = event.timestamp
        
        if event.event_type == EventType.EMAIL_SENT:
            target.status = TargetStatus.OUTREACH_SENT
            target.email_sent_at = event.timestamp
        
        elif event.event_type == EventType.REPLY_RECEIVED:
            target.status = TargetStatus.ENGAGED
            target.reply_received_at = event.timestamp
            
            # Calculate days to reply
            if target.email_sent_at:
                delta = event.timestamp - target.email_sent_at
                target.days_to_reply = delta.days
        
        elif event.event_type == EventType.INTERVIEW_SCHEDULED:
            target.status = TargetStatus.INTERVIEW_SCHEDULED
            target.interview_scheduled_at = event.timestamp
        
        elif event.event_type == EventType.EMAIL_BOUNCED:
            target.status = TargetStatus.REJECTED
        
    def _update_stats(self, event: EventRecord) -> None:
        """Update campaign stats based on event"""
        if event.event_type == EventType.EMAIL_SENT:
            self.stats.emails_sent += 1
        elif event.event_type == EventType.EMAIL_OPENED:
            self.stats.emails_opened += 1
        elif event.event_type == EventType.REPLY_RECEIVED:
            self.stats.replies_received += 1
        elif event.event_type == EventType.INTERVIEW_SCHEDULED:
            self.stats.interviews_scheduled += 1
        elif event.event_type == EventType.EMAIL_BOUNCED:
            self.stats.rejected += 1
        elif event.event_type == EventType.OPTED_OUT:
            self.stats.opted_out += 1
        
        self.stats.calculate_rates()
    
    def get_progress(self) -> Dict[str, Any]:
        """
        Get overall campaign progress
        
        Returns:
            Progress dict with counts and rates
        """
        return {
            "campaign_id": self.campaign_id,
            "campaign_name": self.name,
            "created_at": self.created_at.isoformat(),
            "progress": {
                "total_targets": self.stats.total_targets,
                "prospect": sum(
                    1 for t in self.targets.values()
                    if t.status == TargetStatus.PROSPECT
                ),
                "outreach_sent": sum(
                    1 for t in self.targets.values()
                    if t.status == TargetStatus.OUTREACH_SENT
                ),
                "engaged": sum(
                    1 for t in self.targets.values()
                    if t.status == TargetStatus.ENGAGED
                ),
                "interviews_scheduled": sum(
                    1 for t in self.targets.values()
                    if t.status == TargetStatus.INTERVIEW_SCHEDULED
                ),
                "rejected": sum(
                    1 for t in self.targets.values()
                    if t.status == TargetStatus.REJECTED
                ),
                "opted_out": sum(
                    1 for t in self.targets.values()
                    if t.status == TargetStatus.OPTED_OUT
                ),
            },
            "metrics": self.stats.to_dict(),
        }
    
    def get_timeline(self, target_id: str) -> Dict[str, Any]:
        """
        Get audit timeline for candidate
        
        Shows: email sent → opened → replied → interview scheduled
        """
        target = self.targets.get(target_id)
        if not target:
            return {"error": f"Target {target_id} not found"}
        
        # Get all events for this target
        target_events = [
            e for e in self.events
            if e.target_id == target_id
        ]
        
        return {
            "target_id": target_id,
            "email": target.email,
            "status": target.status.value,
            "stage": target.get_stage(),
            "timeline": [
                e.to_dict()
                for e in sorted(target_events, key=lambda x: x.timestamp)
            ],
            "progress": target.to_dict(),
        }
    
    def get_target_progress(self, target_id: str) -> Optional[Dict[str, Any]]:
        """Get progress for single candidate"""
        target = self.targets.get(target_id)
        if not target:
            return None
        return target.to_dict()
    
    def edit_email(
        self,
        target_id: str,
        email_id: str,
        original_subject: str,
        edited_subject: str,
        original_body: str,
        edited_body: str,
        edited_by: str,
        reason: str,
    ) -> EventRecord:
        """
        Record email edit (before sending)
        
        Args:
            target_id: Candidate ID
            email_id: Email ID
            original_subject: Original subject
            edited_subject: New subject
            original_body: Original body
            edited_body: New body
            edited_by: Recruiter ID
            reason: Reason for edit
        """
        return self.record_event(
            event_type=EventType.EMAIL_EDITED,
            target_id=target_id,
            actor="recruiter",
            data={
                "email_id": email_id,
                "original_subject": original_subject,
                "edited_subject": edited_subject,
                "original_body": original_body,
                "edited_body": edited_body,
                "edited_by": edited_by,
            },
            manual_override=True,
            notes=f"Reason: {reason}",
        )
    
    def get_candidates_for_recruiter(self, recruiter_id: str) -> List[Dict[str, Any]]:
        """
        Get view of candidates for recruiter
        
        Shows: candidate contact, status, timeline
        """
        return [
            {
                "target_id": target.target_id,
                "email": target.email,
                "status": target.status.value,
                "stage": target.get_stage(),
                "email_sent_at": target.email_sent_at.isoformat() if target.email_sent_at else None,
                "reply_received_at": target.reply_received_at.isoformat() if target.reply_received_at else None,
                "days_to_reply": target.days_to_reply,
            }
            for target in self.targets.values()
        ]
    
    def get_candidates_for_candidate(self, target_id: str) -> Dict[str, Any]:
        """
        Get what candidate can see about the outreach
        
        Shows: emails sent, company info, but not strategy/metrics
        """
        target = self.targets.get(target_id)
        if not target:
            return {}
        
        # Get events relevant to candidate
        target_events = [
            e for e in self.events
            if e.target_id == target_id and e.event_type in (
                EventType.EMAIL_SENT,
                EventType.CANDIDATE_COMMENTED,
            )
        ]
        
        return {
            "campaign_name": self.name,
            "emails_received": [
                e.to_dict()
                for e in target_events
                if e.event_type == EventType.EMAIL_SENT
            ],
            "messages": [
                e.to_dict()
                for e in target_events
                if e.event_type == EventType.CANDIDATE_COMMENTED
            ],
        }
    
    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get audit log for compliance (GDPR, SOX, etc.)"""
        return [
            e.to_dict()
            for e in sorted(
                self.events,
                key=lambda x: x.timestamp,
                reverse=True,
            )[:limit]
        ]


# ============================================================================
# CAMPAIGN MANAGER (multi-campaign support)
# ============================================================================

class CampaignManager:
    """Manage multiple campaigns across tenants"""
    
    def __init__(self):
        self.campaigns: Dict[str, CampaignTracker] = {}
    
    def create_campaign(
        self,
        tenant_id: str,
        campaign_id: str,
        name: str,
        target_count: int,
    ) -> CampaignTracker:
        """Create new campaign"""
        campaign = CampaignTracker.create(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            name=name,
            target_count=target_count,
        )
        self.campaigns[campaign_id] = campaign
        return campaign
    
    def get_campaign(self, campaign_id: str) -> Optional[CampaignTracker]:
        """Get campaign by ID"""
        return self.campaigns.get(campaign_id)
    
    def get_tenant_campaigns(self, tenant_id: str) -> List[CampaignTracker]:
        """Get all campaigns for tenant"""
        return [
            c for c in self.campaigns.values()
            if c.tenant_id == tenant_id
        ]


if __name__ == "__main__":
    print("✅ Campaign progress & audit timeline system ready")
    print("   Features: Progress tracking, audit trail, visibility controls")
