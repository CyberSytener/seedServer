from __future__ import annotations

import logging
import sys

import uvicorn
from pythonjsonlogger import jsonlogger


if __name__ == "__main__":
    # Configure JSON structured logging for application logs
    # We create a custom logging config to ensure JSON formatting for app logs
    # while keeping access logs readable
    
    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
        },
        "handlers": {
            "default": {
                "formatter": "json",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.error": {"level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
        "root": {
            "level": "INFO",
            "handlers": ["default"],
        },
    }
    print("Starting uvicorn...")
    
    # Pre-import to verify routes are registered
    from app.main import app as test_app
    pipeline_routes = [r for r in test_app.routes if 'pipeline' in getattr(r, 'path', '')]
    print(f"DEBUG: Pipeline routes in app before uvicorn.run: {len(pipeline_routes)}")
    for r in pipeline_routes:
        print(f"  - {r.path}")
    
    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            log_config=LOGGING_CONFIG
        )
    except Exception as e:
        print(f"Error starting uvicorn: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
