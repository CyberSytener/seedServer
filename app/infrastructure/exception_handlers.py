"""Centralised exception handlers for the FastAPI application."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def register_exception_handlers(app: FastAPI, *, public_mode: bool) -> None:
    """Register custom HTTP / catch-all exception handlers on *app*."""

    def _persona_error(status_code: int, detail: Any, path: str) -> Dict[str, Any]:
        default_msg = "The digital kitchen is locked, chef. Please log in."
        if status_code == 404:
            default_msg = "Recipe route not found in the kitchen map."
        elif status_code == 403:
            default_msg = "Access denied. This station is for authorized chefs only."
        payload: Dict[str, Any] = {
            "detail": detail,
            "persona_message": default_msg,
        }
        if not public_mode:
            # Log debug details server-side only — never expose paths to the client
            logging.debug(
                "Request error: status=%s path=%s reason=%s",
                status_code, path, detail,
            )
        return payload

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code in (401, 403, 404):
            return JSONResponse(
                status_code=exc.status_code,
                content=_persona_error(exc.status_code, exc.detail, str(request.url.path)),
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code in (401, 403, 404):
            return JSONResponse(
                status_code=exc.status_code,
                content=_persona_error(exc.status_code, exc.detail, str(request.url.path)),
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        """Catch-all for unhandled exceptions — never leak stack traces to clients."""
        logging.error(
            "Unhandled exception on %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "internal_server_error"},
        )
