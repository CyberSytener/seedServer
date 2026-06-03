"""Deprecated shim — use ``app.core.rate_limiter`` (sync) or
``app.core.rate_limit`` (async Redis-backed) instead."""
import warnings as _w
_w.warn(
    "app.rate_limiter is deprecated; use app.core.rate_limiter or app.core.rate_limit",
    DeprecationWarning,
    stacklevel=2,
)
try:
    from app.core.rate_limiter import DEFAULT_LIMITS, RateLimitConfig, RateLimiter, rate_limit_middleware
except ImportError:  # pragma: no cover
    raise ImportError(
        "Could not import from app.core.rate_limiter. "
        "Use app.core.rate_limit (async) directly."
    )

__all__ = ["DEFAULT_LIMITS", "RateLimitConfig", "RateLimiter", "rate_limit_middleware"]
