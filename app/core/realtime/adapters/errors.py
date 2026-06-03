"""Shared adapter error types used by core and infrastructure."""

from __future__ import annotations


class AdapterError(Exception):
    """Base exception for adapter failures."""


class TransientAdapterError(AdapterError):
    """Transient error (temporary, can retry)."""


class PermanentAdapterError(AdapterError):
    """Permanent error (won't succeed on retry)."""
