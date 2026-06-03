"""Adapter interfaces and base errors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging

from app.core.realtime.adapters.errors import (
    AdapterError,
    PermanentAdapterError,
    TransientAdapterError,
)


logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {
    "password",
    "token",
    "authorization",
    "api_key",
    "card",
    "card_number",
    "cvv",
    "cvc",
    "email",
    "ssn",
    "secret",
    "access_token",
    "refresh_token",
}


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, val in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = "***"
            else:
                redacted[key] = _redact_payload(val)
        return redacted
    if isinstance(value, list):
        return [_redact_payload(v) for v in value]
    return value


class Adapter(ABC):
    """Abstract base for all external adapters."""

    @abstractmethod
    async def reserve(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def confirm(
        self,
        original_payload: Dict[str, Any],
        confirm_payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def compensate(
        self,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError
