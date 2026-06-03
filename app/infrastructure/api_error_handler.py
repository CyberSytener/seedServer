"""Reusable API exception-handler decorator.

Usage
-----
    from app.infrastructure.api_error_handler import api_route

    @router.get("/items")
    @api_route(logger, context="list_items")
    async def list_items(request: Request):
        ...

The decorator catches *any* unhandled exception, logs it with structured
context (user, path, method, request-id), and returns a clean 500 response.
``HTTPException`` instances are re-raised untouched.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def api_route(
    logger: logging.Logger,
    *,
    context: str = "",
) -> Callable:
    """Decorator factory that wraps a FastAPI route handler with structured
    error logging and a clean 500 fallback.

    Parameters
    ----------
    logger:
        The module-level logger to use for error reporting.
    context:
        A short human-readable label for the operation (e.g. ``"list_items"``).
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Attempt to extract Request from args/kwargs for logging context
            request: Request | None = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            try:
                return await fn(*args, **kwargs)
            except HTTPException:
                raise  # Let FastAPI handle HTTP exceptions normally
            except Exception as exc:
                extra: dict[str, Any] = {"context": context or fn.__name__}
                if request is not None:
                    extra["method"] = request.method
                    extra["path"] = str(request.url.path)
                    extra["request_id"] = request.headers.get("x-request-id", "")
                    # Safely extract user_id from request state if present
                    user_id = getattr(getattr(request, "state", None), "user_id", None)
                    if user_id:
                        extra["user_id"] = user_id

                logger.error(
                    "Unhandled error in %s: %s",
                    context or fn.__name__,
                    exc,
                    exc_info=True,
                    extra=extra,
                )
                return JSONResponse(
                    status_code=500,
                    content={"detail": "internal_server_error"},
                )

        return wrapper

    return decorator
