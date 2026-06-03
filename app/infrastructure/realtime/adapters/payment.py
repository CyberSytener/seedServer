"""Mock payment adapter."""

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from .base import Adapter, PermanentAdapterError, TransientAdapterError, _redact_payload


logger = logging.getLogger(__name__)


class PaymentAdapter(Adapter):
    """Mock payment adapter (for future use)."""

    def __init__(self, logger_instance=None):
        self.logger = logger_instance or logger
        self.transactions: Dict[str, Dict[str, Any]] = {}

    async def reserve(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            self.logger.info("Payment adapter: Authorizing %s", _redact_payload(payload))

            import time
            tx_id = f"AUTH_{int(time.time() * 1000)}"

            self.transactions[tx_id] = {
                "status": "authorized",
                "payload": payload,
            }

            return {
                "transaction_id": tx_id,
                "status": "authorized",
                "amount": payload.get("amount", 0),
            }

        except Exception as e:
            raise TransientAdapterError(f"Authorization failed: {e}")

    async def confirm(
        self,
        original_payload: Dict[str, Any],
        confirm_payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            self.logger.info("Payment adapter: Capturing %s", _redact_payload(confirm_payload))

            tx_id = confirm_payload.get("transaction_id")
            if not tx_id or tx_id not in self.transactions:
                raise PermanentAdapterError("Transaction not found")

            self.transactions[tx_id]["status"] = "captured"

            return {"transaction_id": tx_id, "status": "captured"}

        except Exception as e:
            raise PermanentAdapterError(f"Capture failed: {e}")

    async def compensate(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            self.logger.warning("Payment adapter: Refunding")

            refunded_count = 0
            for tx_id, tx in list(self.transactions.items()):
                if tx["payload"] == payload and tx["status"] in ("authorized", "captured"):
                    tx["status"] = "refunded"
                    refunded_count += 1

            return {"status": "refunded", "refunded_count": refunded_count}

        except Exception as e:
            self.logger.warning("Refund error: %s", e)
            return {"status": "error", "error": str(e)}
