"""Compatibility shim for adapters package."""

from app.infrastructure.realtime.adapters import (
    Adapter,
    AdapterError,
    TransientAdapterError,
    PermanentAdapterError,
    BookingAdapter,
    CalendarAdapter,
    PaymentAdapter,
)

__all__ = [
    "Adapter",
    "AdapterError",
    "TransientAdapterError",
    "PermanentAdapterError",
    "BookingAdapter",
    "CalendarAdapter",
    "PaymentAdapter",
]

