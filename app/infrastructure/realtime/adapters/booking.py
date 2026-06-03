"""Mock booking adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import logging

from .base import Adapter, PermanentAdapterError, _redact_payload


logger = logging.getLogger(__name__)


class BookingAdapter(Adapter):
    """Mock booking adapter (for testing)."""

    def __init__(self, logger_instance=None):
        self.logger = logger_instance or logger
        self.reservations: Dict[str, Dict[str, Any]] = {}

    async def reserve(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            import time

            self.logger.info("Booking adapter: Reserving %s", _redact_payload(payload))

            reservation_id = f"RESV_{int(time.time() * 1000)}"

            self.reservations[reservation_id] = {
                "status": "pending",
                "payload": payload,
                "created_at": time.time(),
            }

            self.logger.info("Reservation created: %s", reservation_id)

            return {
                "reservation_id": reservation_id,
                "status": "pending",
                "price": payload.get("price", 0),
            }

        except Exception as e:
            self.logger.error("Reserve failed: %s", e)
            raise PermanentAdapterError(f"Reserve failed: {e}")

    async def confirm(
        self,
        original_payload: Dict[str, Any],
        confirm_payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            self.logger.info("Booking adapter: Confirming %s", _redact_payload(confirm_payload))

            reservation_id = confirm_payload.get("reservation_id")
            if not reservation_id or reservation_id not in self.reservations:
                raise PermanentAdapterError("Reservation not found")

            self.reservations[reservation_id]["status"] = "confirmed"
            booking_id = f"BK_{reservation_id[5:]}"

            result = {
                "booking_id": booking_id,
                "reservation_id": reservation_id,
                "status": "confirmed",
                "details": {
                    **original_payload,
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                },
            }

            self.logger.info("Booking confirmed: %s", booking_id)
            return result

        except Exception as e:
            self.logger.error("Confirm failed: %s", e)
            raise PermanentAdapterError(f"Confirm failed: {e}")

    async def compensate(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            self.logger.warning("Booking adapter: Compensating %s", _redact_payload(payload))

            cancelled_count = 0
            for rid, rec in list(self.reservations.items()):
                if rec["payload"] == payload and rec["status"] == "pending":
                    rec["status"] = "cancelled"
                    cancelled_count += 1

            result = {
                "status": "cancelled",
                "cancelled_count": cancelled_count,
            }

            self.logger.info("Compensation done: %s reservations cancelled", cancelled_count)
            return result

        except Exception as e:
            self.logger.warning("Compensation error (non-fatal): %s", e)
            return {"status": "error", "error": str(e)}
