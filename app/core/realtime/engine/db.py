"""Compatibility bridge for DB helpers."""

from __future__ import annotations

from app.infrastructure.realtime.engine.db import AsyncPGPoolProxy


__all__ = ["AsyncPGPoolProxy"]
