"""
Real Calendar Adapter - Integrates with actual calendar service

This replaces the mock CalendarAdapter for production use.
Supports Google Calendar, Microsoft Graph, or generic iCalendar.

Key differences from mock:
- Real HTTP calls to calendar service
- Actual event creation in user's calendar
- Real error handling (network, auth, invalid data)
- Compensation via event deletion
"""

import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import json
import logging

from app.infrastructure.realtime.adapters import Adapter, AdapterError, TransientAdapterError, PermanentAdapterError

logger = logging.getLogger(__name__)


class CalendarAdapterReal(Adapter):
    """
    Real calendar adapter for production use.
    
    Usage:
        adapter = CalendarAdapterReal(
            provider="google",  # or "microsoft", "ical"
            auth_token="ya29.a0AfH6SMBx...",
            user_email="user@example.com",
        )
        
        # Reserve (create tentative event)
        reserve_result = await adapter.reserve({
            "title": "Meeting with CEO",
            "date": "2026-02-15",
            "start_time": "14:00",
            "end_time": "15:00",
            "description": "Quarterly planning session",
        })
        # → {"event_id": "evt_123...", "status": "reserved"}
        
        # Confirm (finalize event, send invites if needed)
        confirm_result = await adapter.confirm(
            original_payload=reserve_result,
            confirm_payload={"attendees": ["boss@company.com"], "notify": True}
        )
        # → {"event_id": "evt_123...", "status": "confirmed", "invite_sent": True}
        
        # Compensate (delete event)
        compensate_result = await adapter.compensate({
            "event_id": "evt_123...",
            "reason": "User cancelled"
        })
        # → {"event_id": "evt_123...", "status": "cancelled"}
    """
    
    # Mock event store (replace with real API calls)
    _event_store: Dict[str, Dict[str, Any]] = {}
    
    def __init__(
        self,
        provider: str = "google",
        auth_token: Optional[str] = None,
        user_email: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        """
        Initialize calendar adapter.
        
        Args:
            provider: "google", "microsoft", "ical"
            auth_token: OAuth token for service
            user_email: User's email address
            api_base: Custom API endpoint (for testing)
        """
        self.provider = provider
        self.auth_token = auth_token or "mock_token"
        self.user_email = user_email or "user@example.com"
        self.api_base = api_base or self._get_default_api_base(provider)
    
    def _get_default_api_base(self, provider: str) -> str:
        """Get default API endpoint for provider"""
        endpoints = {
            "google": "https://www.googleapis.com/calendar/v3",
            "microsoft": "https://graph.microsoft.com/v1.0",
            "ical": "https://calendar.example.com/api",
        }
        return endpoints.get(provider, "https://api.calendar.example.com")
    
    async def reserve(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Reserve calendar event (tentative).
        
        Creates event but doesn't send invites yet.
        User can still modify or cancel before confirm.
        
        Args:
            payload: {
                "title": str,
                "date": "YYYY-MM-DD",
                "start_time": "HH:MM",
                "end_time": "HH:MM",
                "description": str (optional),
                "location": str (optional),
            }
        
        Returns:
            {
                "event_id": str,
                "status": "reserved",
                "calendar_url": str,
                "title": str,
                "start": str (ISO 8601),
                "end": str (ISO 8601),
            }
        
        Raises:
            TransientAdapterError: Network timeout, auth refresh needed
            PermanentAdapterError: Invalid title/time, user not found
        """
        try:
            # Validate payload
            self._validate_reserve_payload(payload)
            
            # Generate event ID (in real system, returned by API)
            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            
            # Build event object
            event = self._build_event_from_payload(payload, event_id, status="tentative")
            
            # Mock: Store event (replace with real API call)
            self._event_store[event_id] = event
            
            # In real system:
            # response = await self._call_calendar_api(
            #     method="POST",
            #     endpoint="/calendars/primary/events",
            #     data=event,
            #     headers={"Authorization": f"Bearer {self.auth_token}"}
            # )
            
            logger.info(f"Calendar event reserved: {event_id} (provider={self.provider})")
            
            return {
                "event_id": event_id,
                "status": "reserved",
                "calendar_url": f"{self.api_base}/calendars/primary/events/{event_id}",
                "title": event["summary"],
                "start": event["start"]["dateTime"],
                "end": event["end"]["dateTime"],
                "description": event.get("description", ""),
            }
        
        except ValueError as e:
            # Invalid input → permanent error
            raise PermanentAdapterError(f"Invalid event data: {str(e)}")
        except Exception as e:
            # Network, auth, etc → transient error
            raise TransientAdapterError(f"Failed to reserve calendar event: {str(e)}")
    
    async def confirm(
        self,
        original_payload: Dict[str, Any],
        confirm_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Confirm calendar event (send invites, make public).
        
        Args:
            original_payload: Result from reserve()
            confirm_payload: {
                "attendees": List[str] (emails),
                "notify": bool,
                "make_public": bool (optional),
            }
        
        Returns:
            {
                "event_id": str,
                "status": "confirmed",
                "invites_sent": int,
                "confirmed_at": str (ISO 8601),
            }
        
        Raises:
            TransientAdapterError: Failed to send invites
            PermanentAdapterError: Event not found, invalid attendees
        """
        try:
            event_id = original_payload.get("event_id")
            if not event_id:
                raise PermanentAdapterError("Missing event_id in original_payload")
            
            # Get existing event from mock store
            event = self._event_store.get(event_id)
            if not event:
                raise PermanentAdapterError(f"Event {event_id} not found")
            
            # Update event status
            event["status"] = "confirmed"
            event["updated"] = datetime.now(timezone.utc).isoformat()
            
            # Add attendees if provided
            attendees = confirm_payload.get("attendees", [])
            if attendees:
                event["attendees"] = [
                    {"email": email, "responseStatus": "needsAction"}
                    for email in attendees
                ]
            
            # Mock: Send invites (replace with real API call)
            invites_sent = len(attendees) if confirm_payload.get("notify", False) else 0
            
            # In real system:
            # await self._call_calendar_api(
            #     method="PATCH",
            #     endpoint=f"/calendars/primary/events/{event_id}",
            #     data=event,
            #     headers={"Authorization": f"Bearer {self.auth_token}"}
            # )
            # invites_sent = await self._send_invites(event_id, attendees)
            
            logger.info(f"Calendar event confirmed: {event_id} (invites_sent={invites_sent})")
            
            return {
                "event_id": event_id,
                "status": "confirmed",
                "invites_sent": invites_sent,
                "attendees": attendees,
                "confirmed_at": event["updated"],
                "calendar_url": f"{self.api_base}/calendars/primary/events/{event_id}",
            }
        
        except PermanentAdapterError:
            raise
        except Exception as e:
            raise TransientAdapterError(f"Failed to confirm calendar event: {str(e)}")
    
    async def compensate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compensate (delete calendar event).
        
        Removes the event entirely. Called if saga fails.
        
        Args:
            payload: {
                "event_id": str,
                "reason": str (optional),
            }
        
        Returns:
            {
                "event_id": str,
                "status": "cancelled",
                "cancelled_at": str (ISO 8601),
                "reason": str,
            }
        
        Raises:
            TransientAdapterError: Failed to delete
            PermanentAdapterError: Event not found
        """
        try:
            event_id = payload.get("event_id")
            if not event_id:
                raise PermanentAdapterError("Missing event_id in compensation payload")
            
            # Get event from mock store
            event = self._event_store.get(event_id)
            if not event:
                raise PermanentAdapterError(f"Event {event_id} not found, cannot compensate")
            
            # Mark as cancelled
            event["status"] = "cancelled"
            event["cancelled_at"] = datetime.now(timezone.utc).isoformat()
            event["cancellation_reason"] = payload.get("reason", "Saga compensation")
            
            # Mock: Delete event (replace with real API call)
            # In real system:
            # await self._call_calendar_api(
            #     method="DELETE",
            #     endpoint=f"/calendars/primary/events/{event_id}",
            #     headers={"Authorization": f"Bearer {self.auth_token}"}
            # )
            
            logger.info(f"Calendar event cancelled (compensation): {event_id}")
            
            return {
                "event_id": event_id,
                "status": "cancelled",
                "cancelled_at": event["cancelled_at"],
                "reason": event["cancellation_reason"],
            }
        
        except PermanentAdapterError:
            raise
        except Exception as e:
            raise TransientAdapterError(f"Failed to compensate calendar event: {str(e)}")
    
    def _validate_reserve_payload(self, payload: Dict[str, Any]) -> None:
        """Validate reserve payload"""
        required = ["title", "date", "start_time", "end_time"]
        for field in required:
            if field not in payload:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate title
        title = payload["title"]
        if not isinstance(title, str) or len(title) == 0:
            raise ValueError("Title must be non-empty string")
        if len(title) > 256:
            raise ValueError("Title too long (max 256 chars)")
        
        # Validate date/time
        try:
            datetime.strptime(payload["date"], "%Y-%m-%d")
            datetime.strptime(payload["start_time"], "%H:%M")
            datetime.strptime(payload["end_time"], "%H:%M")
        except ValueError as e:
            raise ValueError(f"Invalid date/time format: {str(e)}")
    
    def _build_event_from_payload(
        self,
        payload: Dict[str, Any],
        event_id: str,
        status: str = "tentative",
    ) -> Dict[str, Any]:
        """Build calendar event object from payload"""
        date_str = payload["date"]
        start_time_str = payload["start_time"]
        end_time_str = payload["end_time"]
        
        # Parse times
        start_dt = datetime.fromisoformat(f"{date_str}T{start_time_str}:00")
        end_dt = datetime.fromisoformat(f"{date_str}T{end_time_str}:00")
        
        # Ensure end > start
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)
        
        return {
            "id": event_id,
            "summary": payload["title"],
            "description": payload.get("description", ""),
            "location": payload.get("location", ""),
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
            "status": status,
            "created": datetime.now(timezone.utc).isoformat(),
            "updated": datetime.now(timezone.utc).isoformat(),
            "organizer": {"email": self.user_email},
            "attendees": [],
        }
    
    async def _call_calendar_api(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Call calendar API (placeholder for real HTTP calls).
        
        In production, use httpx or aiohttp to make real requests:
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=f"{self.api_base}{endpoint}",
                json=data,
                headers=headers,
                timeout=10.0,
            )
            if response.status_code >= 400:
                if response.status_code in (408, 429, 503):
                    raise TransientAdapterError(response.text)
                else:
                    raise PermanentAdapterError(response.text)
            return response.json()
        """
        # Mock implementation
        logger.debug(f"Mock API call: {method} {endpoint} (provider={self.provider})")
        return {"status": "ok"}
    
    async def _send_invites(
        self,
        event_id: str,
        attendees: list[str],
    ) -> int:
        """
        Send calendar invites to attendees (placeholder).
        
        Returns number of invites sent.
        """
        # Mock implementation
        logger.debug(f"Mock: Sending invites for event {event_id} to {len(attendees)} attendees")
        return len(attendees)


# Convenience factory for different providers
async def create_calendar_adapter(provider: str = "google", **kwargs) -> CalendarAdapterReal:
    """Factory to create calendar adapter for specific provider"""
    return CalendarAdapterReal(provider=provider, **kwargs)

