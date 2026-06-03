"""CORS middleware configuration for the FastAPI application."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.settings import Settings

_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
_ALLOWED_HEADERS = [
    "authorization",
    "content-type",
    "x-request-id",
    "x-admin-key",
    "x-api-key",
    "x-user-id",
    "accept",
    "origin",
]


def _validate_origin(origin: str) -> bool:
    """Return *True* if *origin* looks like a valid HTTP(S) URL."""
    origin = origin.strip()
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def configure_cors(app: FastAPI, settings: Settings) -> None:
    """Apply the correct CORS middleware based on *settings*."""
    neoeats_origins = ["https://neoeats.no", "https://www.neoeats.no"]
    localhost_origins: list[str] = []
    if not settings.is_production and not settings.public_mode:
        localhost_origins = ["http://localhost:3000", "http://localhost:5173"]

    if settings.public_mode:
        public_origins = [
            origin.strip()
            for origin in settings.cors_origins.split(",")
            if _validate_origin(origin)
        ]
        for origin in neoeats_origins:
            if origin not in public_origins:
                public_origins.append(origin)
        if not public_origins:
            public_origins = [*neoeats_origins]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=public_origins,
            allow_credentials=True,
            allow_methods=_ALLOWED_METHODS,
            allow_headers=_ALLOWED_HEADERS,
        )
    elif settings.cors_dev_mode:
        if settings.is_production or settings.public_mode:
            raise RuntimeError("CORS dev mode must not be enabled in production")
        logging.warning("CORS_DEV_MODE enabled — restrict to local development only")
        # Only allow localhost and private-network origins; no shared tunnel domains
        allow_origin_regex = (
            r"^https?://("
            r"localhost|127\.0\.0\.1|"
            r"10(?:\.\d{1,3}){3}|"
            r"192\.168(?:\.\d{1,3}){2}|"
            r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
            r")(:\d+)?$"
        )
        allow_origins_list = [*neoeats_origins, *localhost_origins]
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=allow_origin_regex,
            allow_origins=allow_origins_list,
            allow_credentials=True,
            allow_methods=_ALLOWED_METHODS,
            allow_headers=_ALLOWED_HEADERS,
        )
    elif settings.cors_origins:
        prod_origins = [
            origin.strip()
            for origin in settings.cors_origins.split(",")
            if _validate_origin(origin)
        ]
        for origin in neoeats_origins:
            if origin not in prod_origins:
                prod_origins.append(origin)
        if prod_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=prod_origins,
                allow_credentials=True,
                allow_methods=_ALLOWED_METHODS,
                allow_headers=_ALLOWED_HEADERS,
            )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[*neoeats_origins],
            allow_credentials=True,
            allow_methods=_ALLOWED_METHODS,
            allow_headers=_ALLOWED_HEADERS,
        )
