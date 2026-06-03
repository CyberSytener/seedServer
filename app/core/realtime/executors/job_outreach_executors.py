"""
Job Outreach Executors - Wire integration clients to action contracts

Executors implement the actual action workflows:
- SendOutreachEmail: Send email via Outlook, track message ID
- MonitorInbox: Poll inbox for replies
- ParseReply: Extract candidate feedback from reply
- ScheduleInterview: Create calendar event, notify attendees

Pattern:
1. Executor.execute(action_request) → calls integration client
2. Integration client → real-world API (Graph, Calendar, etc)
3. Store result in database (EmailEvent, ReplyEvent, etc)
4. Update action status

Requires:
- OutlookEmailClient with token store
- InboxPollingService
- OutlookCalendarClient
- JobAutomationRepositoryService
"""

from typing import Optional, Any, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# EXECUTOR BASE CLASS
# ============================================================================

class JobOutreachExecutor(ABC):
    """Base executor for job automation actions"""
    
    def __init__(self, repository_service, integration_clients: Dict[str, Any]):
        """
        Args:
            repository_service: JobAutomationRepositoryService
            integration_clients: Dict with keys like:
                - 'outlook_email': OutlookEmailClient
                - 'outlook_calendar': OutlookCalendarClient
                - 'inbox_polling': InboxPollingService
        """
        self.repo = repository_service
        self.clients = integration_clients
    
    @abstractmethod
    def execute(self, action_request: Any) -> Dict[str, Any]:
        """Execute the action and return result"""
        pass


# ============================================================================
# SEND OUTREACH EMAIL EXECUTOR
# ============================================================================

class SendOutreachEmailExecutor(JobOutreachExecutor):
    """
    Execute SendOutreachEmail action
    
    Workflow:
    1. Get recruiter's Outlook token
    2. Build email content
    3. Send via Graph API
    4. Get message_id
    5. Store EmailEvent in database
    6. Update target status to "email_sent"
    
    Idempotency:
    - Check if already sent (EmailEvent exists)
    - Use idempotency_key in Graph API headers
    """
    
    def execute(self, action_request) -> Dict[str, Any]:
        """
        Args:
            action_request: SendOutreachEmail contract
                - target_id: str
                - subject: str
                - body: str
                - recruiter_user_id: str (OAuth user)
        
        Returns:
            {
                'status': 'success'|'error',
                'email_id': str (our database ID),
                'graph_message_id': str (Graph message ID),
                'sent_at': datetime,
                'error': Optional[str]
            }
        """
        target_id = action_request.target_id
        subject = action_request.subject
        body = action_request.body
        recruiter_user_id = action_request.recruiter_user_id
        
        try:
            # ============================================================
            # STEP 1: Check idempotency (already sent?)
            # ============================================================
            existing_events = self.repo.email_events.list_by_target(target_id)
            if existing_events:
                logger.info(f"⚠️  Email already sent for target {target_id}")
                event = existing_events[0]
                return {
                    'status': 'already_sent',
                    'email_id': event.email_id,
                    'graph_message_id': event.graph_message_id,
                    'sent_at': event.sent_at,
                }
            
            # ============================================================
            # STEP 2: Get Outlook client and recipient email
            # ============================================================
            outlook_client = self.clients.get('outlook_email')
            if not outlook_client:
                raise ValueError("Outlook email client not configured")
            
            # Get target (contains recipient email)
            target = self.repo.targets.get_by_id(target_id)
            if not target:
                raise ValueError(f"Target {target_id} not found")
            
            # ============================================================
            # STEP 3: Send email via Outlook Graph API
            # ============================================================
            send_result = outlook_client.send_email(
                user_id=recruiter_user_id,
                recipient=target.target_email,
                subject=subject,
                body=body,
                idempotency_key=f"target_{target_id}_{datetime.now().isoformat()}",
            )
            
            # ============================================================
            # STEP 4: Store EmailEvent in database
            # ============================================================
            email_event = self.repo.email_events.create(
                email_id=self._generate_uuid(),
                target_id=target_id,
                campaign_id=target.campaign_id,
                direction="outgoing",
                subject=subject,
                body_preview=body[:200],
                graph_message_id=send_result.message_id,
                sent_at=send_result.sent_at,
                status="sent",
            )
            
            # ============================================================
            # STEP 5: Update target status
            # ============================================================
            self.repo.targets.update_status(target_id, "email_sent")
            self.repo.commit()
            
            logger.info(f"✅ Email sent to {target.target_email} (msg_id={send_result.message_id})")
            
            return {
                'status': 'success',
                'email_id': email_event.email_id,
                'graph_message_id': send_result.message_id,
                'sent_at': send_result.sent_at,
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to send email for target {target_id}: {e}")
            self.repo.rollback()
            return {
                'status': 'error',
                'error': str(e),
            }
    
    @staticmethod
    def _generate_uuid() -> str:
        import uuid
        return str(uuid.uuid4())


# ============================================================================
# MONITOR INBOX EXECUTOR
# ============================================================================

class MonitorInboxExecutor(JobOutreachExecutor):
    """
    Execute MonitorInbox action
    
    Workflow:
    1. Get all active campaigns
    2. For each recruiter:
       - Get Outlook token
       - Poll inbox (delta query - only new/changed emails)
       - Find replies to our sent emails
       - Create ReplyEvent for each reply
    3. Update target status to "replied"
    
    Efficiency:
    - Delta queries (only fetch changed emails since last check)
    - Batch polling (check all recruiters in one go)
    - Skip already-processed emails (conversation_id tracking)
    """
    
    def execute(self, action_request) -> Dict[str, Any]:
        """
        Args:
            action_request: MonitorInbox contract
                - recruiter_user_id: str (OAuth user)
                - campaign_id: Optional[str] (or all active)
        
        Returns:
            {
                'status': 'success'|'error',
                'replies_found': int,
                'targets_updated': int,
                'error': Optional[str]
            }
        """
        recruiter_user_id = action_request.recruiter_user_id
        campaign_id = getattr(action_request, 'campaign_id', None)
        
        try:
            # ============================================================
            # STEP 1: Get inbox polling service
            # ============================================================
            polling_service = self.clients.get('inbox_polling')
            if not polling_service:
                raise ValueError("Inbox polling service not configured")
            
            # ============================================================
            # STEP 2: Poll inbox (delta query - efficient)
            # ============================================================
            reply_mappings = polling_service.poll_inbox(
                user_id=recruiter_user_id,
                campaign_id=campaign_id,
            )
            
            # ============================================================
            # STEP 3: For each reply, create ReplyEvent and update target
            # ============================================================
            targets_updated = 0
            
            for mapping in reply_mappings:
                try:
                    # Create ReplyEvent
                    reply_event = self.repo.reply_events.create(
                        reply_id=self._generate_uuid(),
                        target_id=mapping.target_id,
                        campaign_id=mapping.campaign_id,
                        incoming_email_id=mapping.incoming_email_id,
                        feedback_text=mapping.feedback_preview,
                        received_at=mapping.received_at,
                        status="pending_review",
                    )
                    
                    # Update target status
                    self.repo.targets.update_status(mapping.target_id, "replied")
                    targets_updated += 1
                    
                    logger.info(f"✅ Reply detected for target {mapping.target_id}")
                
                except Exception as e:
                    logger.error(f"❌ Error processing reply for target {mapping.target_id}: {e}")
                    self.repo.rollback()
            
            self.repo.commit()
            
            return {
                'status': 'success',
                'replies_found': len(reply_mappings),
                'targets_updated': targets_updated,
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to monitor inbox for {recruiter_user_id}: {e}")
            self.repo.rollback()
            return {
                'status': 'error',
                'error': str(e),
            }
    
    @staticmethod
    def _generate_uuid() -> str:
        import uuid
        return str(uuid.uuid4())


# ============================================================================
# PARSE REPLY EXECUTOR
# ============================================================================

class ParseReplyExecutor(JobOutreachExecutor):
    """
    Execute ParseReply action
    
    Workflow:
    1. Get ReplyEvent from database
    2. Fetch full email body (only when parsing)
    3. Extract candidate feedback
       - Interested/Not interested
       - Reasons for rejection
       - Next steps
    4. Update ReplyEvent with parsed data
    5. If interested: Create ScheduleInterview action
    
    Privacy:
    - Only fetch full body when explicitly parsing
    - Don't store full email (only preview)
    """
    
    def execute(self, action_request) -> Dict[str, Any]:
        """
        Args:
            action_request: ParseReply contract
                - reply_id: str
        
        Returns:
            {
                'status': 'success'|'error',
                'feedback': Dict (parsed content),
                'action_triggered': Optional[str],
                'error': Optional[str]
            }
        """
        reply_id = action_request.reply_id
        
        try:
            # ============================================================
            # STEP 1: Get ReplyEvent
            # ============================================================
            reply_event = self.repo.reply_events.get_by_id(reply_id)
            if not reply_event:
                raise ValueError(f"Reply {reply_id} not found")
            
            # ============================================================
            # STEP 2: Fetch full email body (only when parsing)
            # ============================================================
            outlook_client = self.clients.get('outlook_email')
            if not outlook_client:
                raise ValueError("Outlook email client not configured")
            
            email_body = outlook_client.get_email_body(
                user_id=reply_event.recruiter_user_id,
                message_id=reply_event.incoming_email_id,
            )
            
            # ============================================================
            # STEP 3: Parse feedback
            # ============================================================
            parsed_feedback = self._parse_feedback(email_body)
            
            # ============================================================
            # STEP 4: Update ReplyEvent with parsed data
            # ============================================================
            self.repo.reply_events.update_parsed(
                reply_id=reply_id,
                parsed_feedback=parsed_feedback,
                status="reviewed",
            )
            
            # ============================================================
            # STEP 5: If interested, trigger next action
            # ============================================================
            next_action = None
            if parsed_feedback.get('interest_level') == 'high':
                next_action = "schedule_interview"
            
            self.repo.commit()
            
            return {
                'status': 'success',
                'feedback': parsed_feedback,
                'action_triggered': next_action,
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to parse reply {reply_id}: {e}")
            self.repo.rollback()
            return {
                'status': 'error',
                'error': str(e),
            }
    
    @staticmethod
    def _parse_feedback(email_body: str) -> Dict[str, Any]:
        """
        Parse email body for feedback signals
        
        Simple heuristics:
        - Check for "interested", "yes", "let's", "schedule"
        - Check for "not interested", "no", "pass", "not fit"
        - Extract reasons
        """
        body_lower = email_body.lower()
        
        positive_signals = ["interested", "yes", "let's", "schedule", "great", "excited"]
        negative_signals = ["not interested", "no", "pass", "not fit", "thanks but", "unfortunately"]
        
        interest_level = "neutral"
        
        if any(signal in body_lower for signal in positive_signals):
            interest_level = "high"
        elif any(signal in body_lower for signal in negative_signals):
            interest_level = "low"
        
        return {
            'interest_level': interest_level,
            'body_preview': email_body[:500],
            'parsed_at': datetime.now().isoformat(),
        }


# ============================================================================
# SCHEDULE INTERVIEW EXECUTOR
# ============================================================================

class ScheduleInterviewExecutor(JobOutreachExecutor):
    """
    Execute ScheduleInterview action
    
    Workflow:
    1. Get candidate + recruiter info
    2. Find available time slot
    3. Create calendar event:
       - Title: "Interview: {candidate} - {role}"
       - Attendees: candidate email, recruiter email
       - Meeting link: Teams/Google Meet (auto-generated)
    4. Send calendar invites
    5. Store interview event in database
    6. Update target status to "interview_scheduled"
    
    Meeting Links:
    - Outlook Calendar: Auto-generate Teams meeting
    - Google Calendar: Auto-generate Google Meet
    """
    
    def execute(self, action_request) -> Dict[str, Any]:
        """
        Args:
            action_request: ScheduleInterview contract
                - target_id: str
                - candidate_id: str
                - recruiter_user_id: str (OAuth user)
                - interview_time: datetime
                - meeting_type: str ('teams'|'google_meet'|'zoom')
        
        Returns:
            {
                'status': 'success'|'error',
                'event_id': str,
                'calendar_link': str,
                'meeting_link': str,
                'error': Optional[str]
            }
        """
        target_id = action_request.target_id
        candidate_id = action_request.candidate_id
        recruiter_user_id = action_request.recruiter_user_id
        interview_time = action_request.interview_time
        meeting_type = getattr(action_request, 'meeting_type', 'teams')
        
        try:
            # ============================================================
            # STEP 1: Get candidate and target info
            # ============================================================
            candidate = self.repo.candidates.get_by_id(candidate_id)
            target = self.repo.targets.get_by_id(target_id)
            
            if not candidate or not target:
                raise ValueError("Candidate or target not found")
            
            # ============================================================
            # STEP 2: Create calendar event
            # ============================================================
            calendar_client = self.clients.get('outlook_calendar')
            if not calendar_client:
                raise ValueError("Calendar client not configured")
            
            create_result = calendar_client.create_event(
                user_id=recruiter_user_id,
                title=f"Interview: {candidate.name} - {target.target_role}",
                description=f"Interview with candidate: {candidate.email}\n\nRole: {target.target_role}",
                start_time=interview_time,
                end_time=interview_time + timedelta(hours=1),
                attendees=[
                    {
                        'email': candidate.email,
                        'name': candidate.name,
                        'is_organizer': False,
                    },
                    {
                        'email': recruiter_user_id,
                        'name': 'Recruiter',
                        'is_organizer': True,
                    }
                ],
                meeting_link_type=meeting_type,
            )
            
            # ============================================================
            # STEP 3: Store in database
            # ============================================================
            # TODO: Add interview_events table if not exists
            # interview_event = self.repo.interview_events.create(
            #     interview_id=self._generate_uuid(),
            #     target_id=target_id,
            #     campaign_id=target.campaign_id,
            #     scheduled_at=interview_time,
            #     calendar_event_id=create_result.event_id,
            #     meeting_link=create_result.meeting_link,
            #     status='scheduled',
            # )
            
            # ============================================================
            # STEP 4: Update target status
            # ============================================================
            self.repo.targets.update_status(target_id, "interview_scheduled")
            self.repo.commit()
            
            logger.info(f"✅ Interview scheduled for {candidate.name} on {interview_time}")
            
            return {
                'status': 'success',
                'event_id': create_result.event_id,
                'calendar_link': create_result.calendar_link,
                'meeting_link': create_result.meeting_link,
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to schedule interview for target {target_id}: {e}")
            self.repo.rollback()
            return {
                'status': 'error',
                'error': str(e),
            }
    
    @staticmethod
    def _generate_uuid() -> str:
        import uuid
        return str(uuid.uuid4())


# ============================================================================
# EXECUTOR FACTORY
# ============================================================================

class JobOutreachExecutorFactory:
    """Create executors for different action types"""
    
    _executors = {
        'SendOutreachEmail': SendOutreachEmailExecutor,
        'MonitorInbox': MonitorInboxExecutor,
        'ParseReply': ParseReplyExecutor,
        'ScheduleInterview': ScheduleInterviewExecutor,
    }
    
    @classmethod
    def create_executor(
        cls,
        action_type: str,
        repository_service,
        integration_clients: Dict[str, Any],
    ) -> JobOutreachExecutor:
        """
        Create executor for action type
        
        Args:
            action_type: 'SendOutreachEmail', 'MonitorInbox', 'ParseReply', 'ScheduleInterview'
            repository_service: JobAutomationRepositoryService
            integration_clients: Dict with 'outlook_email', 'outlook_calendar', 'inbox_polling'
        """
        executor_class = cls._executors.get(action_type)
        if not executor_class:
            raise ValueError(f"Unknown action type: {action_type}")
        
        return executor_class(repository_service, integration_clients)


if __name__ == "__main__":
    print("✅ Job outreach executors ready")
    print("   Actions: SendOutreachEmail, MonitorInbox, ParseReply, ScheduleInterview")
