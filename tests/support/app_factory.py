from __future__ import annotations

from typing import Dict, Mapping, Set, Tuple
from unittest.mock import patch

from fastapi import FastAPI
from pytest import MonkeyPatch


def _base_env(db_path: str) -> Dict[str, str]:
    return {
        "SEED_DB_PATH": db_path,
        "SEED_REDIS_URL": "redis://localhost:6379/15",
        "SEED_REDIS_NAMESPACE": "seed_test",
        "SEED_ADMIN_KEY": "",
        "SEED_API_KEY_PEPPER": "pepper",
        "SEED_DEFAULT_PROVIDER_FAST": "stub",
        "SEED_DEFAULT_PROVIDER_BATCH": "stub",
        "SEED_METRICS_ENABLED": "0",
        "SEED_ENV": "test",
        "SEED_DEV_CORS": "0",
    }


def create_test_app(
    monkeypatch: MonkeyPatch,
    *,
    db_path: str,
    env_overrides: Mapping[str, str] | None = None,
) -> FastAPI:
    env = _base_env(db_path)
    if env_overrides:
        env.update({k: str(v) for k, v in env_overrides.items()})

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with patch("app.infrastructure.monitoring.monitoring.metrics.init_metrics", lambda *args, **kwargs: None):
        from app.main import create_app

        return create_app()


def route_signatures(app: FastAPI) -> Set[Tuple[str, str]]:
    signatures: Set[Tuple[str, str]] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            signatures.add((method, path))
    return signatures
