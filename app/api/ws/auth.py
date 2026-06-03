"""
JWT authentication for WebSocket handshake.

Re-exported from core security utilities to avoid API->Core dependency.
"""

from app.core.security.jwt import JWTHandler

__all__ = ["JWTHandler"]
