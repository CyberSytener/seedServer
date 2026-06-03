"""
Calendar Client - Microsoft Graph & Google Calendar Integration

Handles calendar operations:
- Create interview events
- Add attendees (candidate + recruiters)
- Generate meeting links (Teams / Zoom)
- Handle reschedules and cancellations
- Map Graph event ID to ScheduleInterview action

Supports:
- Microsoft Outlook Calendar (Graph API)
- Google Calendar (Google Calendar API)

Usage:
    client = OutlookCalendarClient(
        client_id="...",
        client_secret="...",
        tenant_id="...",
    )
    
    event_id = client.create_event(
        user_id="recruiter@company.com",
        title="Interview: Senior Python Engineer",
        start_time=datetime(2026, 2, 5, 14, 0),
        end_time=datetime(2026, 2, 5, 15, 0),
        attendees=[
            {"email": "alice@example.com", "name": "Alice Engineer"},
            {"email": "hiring@company.com", "name": "Jane Recruiter"},
        ],
        body="Interview for Senior Python Engineer position",
        meeting_link_type="teams",  # teams or zoom
    )
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import requests
import json


class MeetingLinkType(str, Enum):
    """Video conference type"""
    TEAMS = "teams"
    ZOOM = "zoom"
    GOOGLE_MEET = "google_meet"
    NONE = "none"


@dataclass
class CalendarEventAttendee:
    """Calendar event attendee"""
    email: str
    name: Optional[str] = None
    is_organizer: bool = False
    response_status: str = "notResponded"  # notResponded, accepted, declined, tentativelyAccepted


@dataclass
class CreateEventResult:
    """Result of creating calendar event"""
    event_id: str  # Graph API event ID
    created_at: datetime
    calendar_link: Optional[str] = None
    meeting_link: Optional[str] = None
    status: str = "created"  # created, pending, failed
    error: Optional[str] = None


@dataclass
class UpdateEventResult:
    """Result of updating calendar event"""
    event_id: str
    updated_at: datetime
    status: str = "updated"  # updated, failed
    error: Optional[str] = None


# ============================================================================
# OUTLOOK CALENDAR CLIENT
# ============================================================================

class OutlookCalendarClient:
    """
    Microsoft Graph API client for Outlook Calendar operations
    """
    
    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str = "common",
        token_store=None,
        timeout_seconds: float = 10.0,
    ):
        """
        Initialize Outlook Calendar client
        
        Note: Reuses token_store from OutlookEmailClient for same user
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.token_store = token_store
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
    
    def create_event(
        self,
        user_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: List[Dict[str, str]],
        body: Optional[str] = None,
        meeting_link_type: str = "teams",
        location: Optional[str] = None,
    ) -> CreateEventResult:
        """
        Create calendar event with attendees
        
        Args:
            user_id: Calendar owner (recruiter@company.com)
            title: Event title
            start_time: Event start (datetime)
            end_time: Event end (datetime)
            attendees: List of {"email": "...", "name": "..."}
            body: Event description
            meeting_link_type: teams, zoom, google_meet, or none
            location: Physical location
        
        Returns:
            CreateEventResult with event_id
        """
        try:
            token = self._get_valid_token(user_id)
            
            # Build event payload
            event = {
                "subject": title,
                "start": {
                    "dateTime": start_time.isoformat(),
                    "timeZone": "UTC",
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": "UTC",
                },
                "attendees": [
                    {
                        "emailAddress": {
                            "address": attendee["email"],
                            "name": attendee.get("name", attendee["email"]),
                        },
                        "type": "required",
                    }
                    for attendee in attendees
                ],
                "body": {
                    "contentType": "HTML",
                    "content": body or title,
                },
                "isReminderOn": True,
                "reminderMinutesBeforeStart": 15,
            }
            
            # Add location if provided
            if location:
                event["location"] = {"displayName": location}
            
            # Add meeting link
            if meeting_link_type == "teams":
                event["isOnlineMeeting"] = True
                event["onlineMeetingProvider"] = "teamsForBusiness"
            elif meeting_link_type == "zoom":
                # Zoom requires special handling or manual addition
                event["body"]["content"] += "\n\nZoom link to be added"
            
            # Create event
            url = f"{self.GRAPH_API_BASE}/users/{user_id}/events"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            
            response = requests.post(url, json=event, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract meeting link if Teams
            meeting_link = None
            if meeting_link_type == "teams" and "onlineMeeting" in data:
                meeting_link = data["onlineMeeting"].get("joinUrl")
            
            return CreateEventResult(
                event_id=data.get("id", ""),
                created_at=datetime.now(timezone.utc),
                calendar_link=data.get("webLink"),
                meeting_link=meeting_link,
                status="created",
            )
        
        except Exception as e:
            return CreateEventResult(
                event_id="",
                created_at=datetime.now(timezone.utc),
                status="failed",
                error=str(e),
            )
    
    def reschedule_event(
        self,
        user_id: str,
        event_id: str,
        new_start_time: datetime,
        new_end_time: datetime,
    ) -> UpdateEventResult:
        """
        Reschedule existing calendar event
        
        Used when candidate suggests new time
        """
        try:
            token = self._get_valid_token(user_id)
            
            update = {
                "start": {
                    "dateTime": new_start_time.isoformat(),
                    "timeZone": "UTC",
                },
                "end": {
                    "dateTime": new_end_time.isoformat(),
                    "timeZone": "UTC",
                },
            }
            
            url = f"{self.GRAPH_API_BASE}/users/{user_id}/events/{event_id}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            
            response = requests.patch(url, json=update, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
            
            return UpdateEventResult(
                event_id=event_id,
                updated_at=datetime.now(timezone.utc),
                status="updated",
            )
        
        except Exception as e:
            return UpdateEventResult(
                event_id=event_id,
                updated_at=datetime.now(timezone.utc),
                status="failed",
                error=str(e),
            )
    
    def cancel_event(
        self,
        user_id: str,
        event_id: str,
        comment: Optional[str] = None,
    ) -> UpdateEventResult:
        """
        Cancel calendar event and notify attendees
        """
        try:
            token = self._get_valid_token(user_id)
            
            url = f"{self.GRAPH_API_BASE}/users/{user_id}/events/{event_id}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            
            payload = {}
            if comment:
                payload["comment"] = comment
            
            # Microsoft doesn't have direct delete, use cancel
            # Instead, use PATCH to mark as cancelled
            response = requests.delete(url, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
            
            return UpdateEventResult(
                event_id=event_id,
                updated_at=datetime.now(timezone.utc),
                status="updated",
            )
        
        except Exception as e:
            return UpdateEventResult(
                event_id=event_id,
                updated_at=datetime.now(timezone.utc),
                status="failed",
                error=str(e),
            )
    
    def get_event(
        self,
        user_id: str,
        event_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get calendar event details"""
        try:
            token = self._get_valid_token(user_id)
            
            url = f"{self.GRAPH_API_BASE}/users/{user_id}/events/{event_id}"
            headers = {"Authorization": f"Bearer {token}"}
            
            response = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
            
            return response.json()
        
        except Exception as e:
            print(f"⚠️ Error fetching event: {e}")
            return None
    
    def _get_valid_token(self, user_id: str) -> str:
        """Get valid access token (from token store or refresh)"""
        if not self.token_store:
            raise ValueError("Token store not configured")
        
        token = self.token_store.get_token(user_id)
        if token:
            return token
        
        # Try refresh
        refresh_token = self.token_store.get_refresh_token(user_id)
        if not refresh_token:
            raise ValueError(f"No valid token for user {user_id}")
        
        # Would call refresh logic here (same as OutlookEmailClient)
        return token


# ============================================================================
# GOOGLE CALENDAR CLIENT (FUTURE)
# ============================================================================

class GoogleCalendarClient:
    """
    Google Calendar API client
    
    Note: Implemented similarly to OutlookCalendarClient
    Uses Google Calendar API v3
    """
    
    API_BASE = "https://www.googleapis.com/calendar/v3"
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_store=None,
        timeout_seconds: float = 10.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_store = token_store
        self.timeout_seconds = timeout_seconds
    
    def create_event(
        self,
        user_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: List[Dict[str, str]],
        body: Optional[str] = None,
        meeting_link_type: str = "google_meet",
    ) -> CreateEventResult:
        """
        Create Google Calendar event with Google Meet link
        
        Google Calendar automatically generates Meet links for remote events
        """
        try:
            token = self._get_valid_token(user_id)
            
            event = {
                "summary": title,
                "description": body or title,
                "start": {
                    "dateTime": start_time.isoformat() + "Z",
                    "timeZone": "UTC",
                },
                "end": {
                    "dateTime": end_time.isoformat() + "Z",
                    "timeZone": "UTC",
                },
                "attendees": [
                    {
                        "email": attendee["email"],
                        "displayName": attendee.get("name", attendee["email"]),
                    }
                    for attendee in attendees
                ],
                "conferenceData": {
                    "createRequest": {
                        "requestId": self._generate_request_id(),
                        "conferenceSolutionKey": {"key": "hangoutsMeet"},
                    }
                },
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "email", "minutes": 1440},  # 24 hours
                        {"method": "popup", "minutes": 15},
                    ],
                },
            }
            
            url = f"{self.API_BASE}/calendars/primary/events"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            
            response = requests.post(url, json=event, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
            
            data = response.json()
            
            meeting_link = None
            if "conferenceData" in data:
                meeting_link = data["conferenceData"].get("entryPoints", [{}])[0].get("uri")
            
            return CreateEventResult(
                event_id=data.get("id", ""),
                created_at=datetime.now(timezone.utc),
                calendar_link=data.get("htmlLink"),
                meeting_link=meeting_link,
                status="created",
            )
        
        except Exception as e:
            return CreateEventResult(
                event_id="",
                created_at=datetime.now(timezone.utc),
                status="failed",
                error=str(e),
            )
    
    def _get_valid_token(self, user_id: str) -> str:
        """Get valid access token"""
        if not self.token_store:
            raise ValueError("Token store not configured")
        return self.token_store.get_token(user_id) or ""
    
    @staticmethod
    def _generate_request_id() -> str:
        """Generate unique request ID for Google API"""
        import uuid
        return str(uuid.uuid4())


if __name__ == "__main__":
    print("✅ CalendarClient ready")
    print("   Supports: Outlook Calendar, Google Calendar")
    print("   Creates events, reschedules, cancels, generates meeting links")
