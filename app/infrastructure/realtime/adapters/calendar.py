"""Mock calendar adapter."""

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from .base import Adapter, PermanentAdapterError, _redact_payload


logger = logging.getLogger(__name__)


class CalendarAdapter(Adapter):
    """Mock calendar adapter (for testing)."""

    def __init__(self, logger_instance=None):
        self.logger = logger_instance or logger
        self.events: Dict[str, Dict[str, Any]] = {}

    async def create(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            self.logger.info("Calendar adapter: Creating event %s", _redact_payload(payload))

            import time
            event_id = f"EVT_{int(time.time() * 1000)}"

            self.events[event_id] = {
                "status": "created",
                "payload": payload,
            }

            result = {
                "event_id": event_id,
                "status": "created",
                "url": f"https://calendar.example.com/events/{event_id}",
            }

            self.logger.info("Event created: %s", event_id)
            return result

        except Exception as e:
            self.logger.error("Create event failed: %s", e)
            raise PermanentAdapterError(f"Create event failed: {e}")

    async def reserve(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self.create(payload)

    async def confirm(
        self,
        original_payload: Dict[str, Any],
        confirm_payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {"status": "already_confirmed"}

    async def compensate(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            self.logger.warning("Calendar adapter: Canceling event")

            cancelled_count = 0
            for eid, evt in list(self.events.items()):
                if evt["payload"] == payload:
                    evt["status"] = "cancelled"
                    cancelled_count += 1

            return {"status": "cancelled", "cancelled_count": cancelled_count}

        except Exception as e:
            self.logger.warning("Cancel event error: %s", e)
            return {"status": "error", "error": str(e)}
