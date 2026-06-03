"""
Inbox Polling Service - Continuous Monitoring

Monitors user inboxes for incoming replies using Graph API delta queries.
Efficiently fetches only new/changed emails and maps them to existing campaigns.

Architecture:
1. Periodic task (every 5 minutes): call poll_inboxes()
2. For each inbox change: map reply to campaign/target
3. Store reply in database (ReplyEvent)
4. Trigger reply parsing (ParseReply action)

Usage:
    service = InboxPollingService(
        email_client=client,
        repository_service=repo,
        parse_reply_executor=executor,
    )
    
    # Run in background (every 5 minutes)
    async def monitor_loop():
        while True:
            await service.poll_all_inboxes()
            await asyncio.sleep(300)  # 5 minutes
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any, Protocol
from datetime import datetime
from dataclasses import dataclass
from app.infrastructure.realtime.integrations.outlook_email_client import (
    OutlookEmailClient,
    EmailMetadata,
)


class JobAutomationRepositoryService(Protocol):
    """Minimal repository facade used by inbox polling."""

    emails: Any
    targets: Any
    replies: Any
    campaigns: Any

    def commit(self) -> None:
        ...


@dataclass
class ReplyMappingResult:
    """Result of mapping a reply to a campaign"""
    found_target: bool
    target_id: Optional[str] = None
    campaign_id: Optional[str] = None
    message: Optional[str] = None


class InboxPollingService:
    """
    Monitors inboxes for incoming replies
    
    Workflow:
    1. Get new emails (delta query)
    2. Check if email is reply to outreach (in-reply-to header)
    3. Map to original target/campaign
    4. Store ReplyEvent in database
    5. Trigger ParseReply action
    """
    
    def __init__(
        self,
        email_client: OutlookEmailClient,
        repository_service: JobAutomationRepositoryService,
    ):
        self.email_client = email_client
        self.repo = repository_service
    
    def poll_inbox(self, user_id: str) -> List[ReplyMappingResult]:
        """
        Poll single user's inbox for new replies
        
        Args:
            user_id: User's email address (user@company.com)
        
        Returns:
            List of ReplyMappingResult (one per email)
        """
        results = []
        
        try:
            # Get new/changed emails via delta query
            delta_result = self.email_client.get_inbox_delta(user_id)
            
            for email_metadata in delta_result.emails:
                # Check if this is a reply to our outreach
                result = self._process_incoming_email(user_id, email_metadata)
                results.append(result)
            
            return results
        
        except Exception as e:
            print(f"⚠️ Error polling inbox for {user_id}: {e}")
            return []
    
    def _process_incoming_email(
        self,
        user_id: str,
        email: EmailMetadata,
    ) -> ReplyMappingResult:
        """
        Process single incoming email
        
        Steps:
        1. Check if it's a reply (in_reply_to set)
        2. Find original outreach email (via in_reply_to message ID)
        3. Map to target/campaign
        4. Store ReplyEvent
        """
        
        # Step 1: Is this a reply?
        if not email.in_reply_to:
            return ReplyMappingResult(
                found_target=False,
                message="Not a reply (no in_reply_to)",
            )
        
        # Step 2: Find the outreach email this is replying to
        original_email_event = self.repo.emails.get_by_outreach_email_id(
            email.in_reply_to
        )
        
        if not original_email_event:
            return ReplyMappingResult(
                found_target=False,
                message=f"Original email not found (id: {email.in_reply_to})",
            )
        
        # Step 3: Get target and campaign
        target_id = original_email_event.target_id
        target = self.repo.targets.get_by_id(target_id)
        
        if not target:
            return ReplyMappingResult(
                found_target=False,
                message=f"Target not found (id: {target_id})",
            )
        
        # Step 4: Get full email body for parsing
        email_body = self.email_client.get_email_body(user_id, email.message_id)
        
        if not email_body:
            return ReplyMappingResult(
                found_target=False,
                message="Could not fetch email body",
            )
        
        # Step 5: Store ReplyEvent
        reply_event = self.repo.replies.create(
            reply_event_id=self._generate_uuid(),
            target_id=target_id,
            candidate_id=target.candidate_id,
            reply_id=self._generate_uuid(),
            incoming_email_id=email.message_id,  # Graph API message ID
            from_email=email.from_email,
            subject=email.subject,
            received_at=email.received_at,
            classification="unclassifiable",  # Will be set by ParseReply
            confidence=0.0,
            original_message=email_body,
            parser_model="pending",
        )
        
        # Step 6: Update target status
        self.repo.targets.update_status(target_id, "replied")
        
        # Commit
        self.repo.commit()
        
        return ReplyMappingResult(
            found_target=True,
            target_id=target_id,
            campaign_id=target.campaign_id,
            message=f"Reply stored (reply_id: {reply_event.reply_event_id})",
        )
    
    @staticmethod
    def _generate_uuid() -> str:
        """Generate UUID"""
        import uuid
        return str(uuid.uuid4())


class BatchInboxPollingService:
    """
    Polls multiple user inboxes in batch
    
    Useful for:
    - Monitoring all company recruiter inboxes
    - Checking multiple campaigns simultaneously
    - Rate-limited API calls
    """
    
    def __init__(
        self,
        email_client: OutlookEmailClient,
        repository_service: JobAutomationRepositoryService,
    ):
        self.single_service = InboxPollingService(email_client, repository_service)
    
    def poll_all_active_campaigns(self) -> Dict[str, List[ReplyMappingResult]]:
        """
        Poll inboxes for all active campaigns
        
        Gets list of recruiter emails from active campaigns, polls each inbox
        
        Returns:
            Dict[recruiter_email] -> List[ReplyMappingResult]
        """
        results = {}
        
        # Get all active campaigns
        campaigns = self.single_service.repo.campaigns.list_active()
        
        # Get unique recruiters (created_by user_id)
        recruiters = set(campaign.created_by for campaign in campaigns)
        
        # Poll each recruiter's inbox
        for recruiter_id in recruiters:
            print(f"📧 Polling inbox for {recruiter_id}...")
            reply_results = self.single_service.poll_inbox(recruiter_id)
            results[recruiter_id] = reply_results
            
            # Log results
            found = sum(1 for r in reply_results if r.found_target)
            print(f"   ✅ {found} replies found")
        
        return results


# ============================================================================
# ASYNC VERSION (For Production)
# ============================================================================

class AsyncInboxPollingService:
    """
    Async version of InboxPollingService for production deployments
    
    Usage (with asyncio):
        service = AsyncInboxPollingService(...)
        
        async def monitor_loop():
            while True:
                await service.poll_all_inboxes()
                await asyncio.sleep(300)  # 5 minutes
        
        # Run in background
        asyncio.create_task(monitor_loop())
    """
    
    def __init__(
        self,
        email_client: OutlookEmailClient,
        repository_service: JobAutomationRepositoryService,
    ):
        self.sync_service = InboxPollingService(email_client, repository_service)
    
    async def poll_all_active_campaigns_async(self) -> Dict[str, List[ReplyMappingResult]]:
        """
        Async version of poll_all_active_campaigns
        
        Polls inboxes concurrently (if async email client available)
        """
        # For now, just wrap sync version
        # In production, use async HTTP client (aiohttp) for parallel requests
        return self.sync_service.poll_all_active_campaigns()


# ============================================================================
# REPLY MATCHING ALGORITHM
# ============================================================================

class ReplyMatcher:
    """
    Advanced reply matching (fallback if in_reply_to not reliable)
    
    Strategies:
    1. in_reply_to field (most reliable)
    2. Conversation ID + sender email matching
    3. Subject line matching (thread subject)
    4. Time-based heuristics (reply within X hours of send)
    """
    
    def __init__(self, repository_service: JobAutomationRepositoryService):
        self.repo = repository_service
    
    def find_original_email(
        self,
        reply: EmailMetadata,
    ) -> Optional[Any]:
        """
        Find original outreach email that this reply corresponds to
        
        Tries multiple strategies in order of confidence
        """
        
        # Strategy 1: Direct in_reply_to
        if reply.in_reply_to:
            email_event = self.repo.emails.get_by_outreach_email_id(reply.in_reply_to)
            if email_event:
                return email_event
        
        # Strategy 2: Conversation ID matching (for thread-based email)
        if reply.conversation_id:
            # Query: find email event with same conversation_id + recipient is reply.from_email
            # (Pseudocode - would need to extend repository)
            pass
        
        # Strategy 3: Subject line matching
        # Strip "Re: " prefix and match subject
        if reply.subject.startswith("Re:"):
            clean_subject = reply.subject[4:].strip()
            # Would search for email with similar subject sent to reply.from_email
            pass
        
        return None


if __name__ == "__main__":
    print("✅ InboxPollingService ready")
    print("   Usage: Monitor inboxes, map replies to campaigns, store ReplyEvents")

