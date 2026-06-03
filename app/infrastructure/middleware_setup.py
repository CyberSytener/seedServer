"""HTTP middleware registration for the FastAPI application."""
from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.authz import resolve_auth_context
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS


def register_middleware(app: FastAPI, *, settings, db) -> None:
    """Register all HTTP middleware on *app*.

    **Execution order (LIFO — last registered wraps outermost):**

    Request → RequestIDMiddleware (outermost, added last via add_middleware)
            → metrics_middleware   (timing + counters)
            → unified_auth_context (populates request.state.auth)
            → security_and_limits  (body-size guard, security headers)
            → route handler

    CORSMiddleware is registered separately in ``configure_cors()`` *before*
    this function is called, so it wraps everything (very outermost layer
    after RequestIDMiddleware).
    """

    @app.middleware("http")
    async def security_and_limits_middleware(request: Request, call_next):
        if settings.public_mode:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > settings.max_request_body_bytes:
                        return JSONResponse(status_code=413, content={"detail": "request body too large"})
                except ValueError:
                    pass

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if settings.public_mode:
            forwarded_proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
            if forwarded_proto == "https":
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains; preload",
                )
        return response

    @app.middleware("http")
    async def unified_auth_context_middleware(request: Request, call_next):
        request.state.auth = None
        path = str(request.url.path or "")
        skip_prefixes = (
            "/health",
            "/docs",
            "/openapi",
            "/redoc",
            "/api/v1/auth/login",
        )
        if not any(path.startswith(prefix) for prefix in skip_prefixes):
            try:
                resolve_auth_context(request, db, required=False)
            except Exception:
                # Best-effort population only; endpoint-level checks enforce access.
                request.state.auth = None
        return await call_next(request)

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            if settings.metrics_enabled:
                path = request.url.path
                method = request.method
                status = response.status_code if response is not None else 500
                dur = max(0.0, time.perf_counter() - start)
                HTTP_LATENCY.labels(path=path, method=method).observe(dur)
                HTTP_REQUESTS.labels(path=path, method=method, status=str(status)).inc()

    # --- X-Request-ID (outermost middleware — added last via add_middleware,
    #     so in Starlette's LIFO model it wraps everything above) ---
    from app.middleware.request_id import RequestIDMiddleware
    app.add_middleware(RequestIDMiddleware)
