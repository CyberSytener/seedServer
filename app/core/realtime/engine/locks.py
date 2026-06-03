"""Compatibility bridge for distributed lock utilities."""

from __future__ import annotations

from app.infrastructure.realtime.engine.locks import DistributedLock


__all__ = ["DistributedLock"]
