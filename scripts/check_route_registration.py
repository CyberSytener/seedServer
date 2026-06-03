"""Route registration sanity checks for CI.

Validates:
- critical API routes are registered
- no duplicate HTTP method/path handlers are present
"""

from __future__ import annotations

import os
import sys
from collections import Counter


def _set_ci_defaults() -> None:
    os.environ.setdefault("SEED_ENV", "test")
    os.environ.setdefault("SEED_DEV", "0")
    os.environ.setdefault("SEED_DB_PATH", ":memory:")
    os.environ.setdefault("SEED_REDIS_URL", "redis://localhost:6379/15")
    os.environ.setdefault("SEED_REDIS_NAMESPACE", "seed_ci")
    os.environ.setdefault("SEED_DEFAULT_PROVIDER_FAST", "stub")
    os.environ.setdefault("SEED_DEFAULT_PROVIDER_BATCH", "stub")
    os.environ.setdefault("SEED_ENABLE_STUB", "1")
    os.environ.setdefault("SEED_ENABLE_LEGACY_X_USER_ID", "0")
    os.environ.setdefault("SEED_DEV_CORS", "0")
    os.environ.setdefault("SEED_SEED_DEV_USERS_ON_STARTUP", "0")
    os.environ.setdefault("SEED_METRICS_ENABLED", "0")
    os.environ.setdefault("JWT_SECRET_KEY", "route-sanity-secret-key-32-bytes-min")


def main() -> int:
    _set_ci_defaults()

    try:
        from app.main import create_app
    except Exception as exc:
        print(f"FAILED: unable to import create_app(): {exc}")
        return 2

    try:
        app = create_app()
    except Exception as exc:
        print(f"FAILED: create_app() raised: {exc}")
        return 2

    registered: list[tuple[str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            registered.append((method, path))

    counts = Counter(registered)
    duplicates = sorted((method, path, count) for (method, path), count in counts.items() if count > 1)

    required_routes = {
        ("GET", "/health"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/v1/actions"),
        ("GET", "/v1/jobs/{job_id}"),
        ("POST", "/v1/lessons/generate"),
        ("POST", "/v1/diagnostics/generate"),
        ("POST", "/v1/admin/mode"),
    }
    missing = sorted(route for route in required_routes if route not in counts)

    if missing:
        print("FAILED: missing required routes:")
        for method, path in missing:
            print(f"  - {method} {path}")

    if duplicates:
        print("FAILED: duplicate method/path registrations:")
        for method, path, count in duplicates:
            print(f"  - {method} {path} ({count} registrations)")

    if missing or duplicates:
        return 1

    print(f"Route sanity passed ({len(counts)} unique HTTP method/path pairs).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
