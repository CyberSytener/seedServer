from __future__ import annotations

import asyncio
from typing import Any

import pytest

from fastapi import HTTPException

from app.api.saga_blueprints import _run_saga
from app.core.blocks import build_default_registry
from app.core.realtime.sagas.flows.dynamic_saga import ExecutionMode


def test_live_run_without_postgres_config_fails_fast(monkeypatch) -> None:
    monkeypatch.delenv("SEED_SAGA_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    async def _should_not_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("AsyncPGDatabase.get_shared must not be called without DSN")

    monkeypatch.setattr("app.api.saga_blueprints.AsyncPGDatabase.get_shared", _should_not_connect)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            _run_saga(
                {"steps": []},
                {"user_id": "u1"},
                build_default_registry(),
                execution_mode=ExecutionMode.LIVE,
            )
        )
    assert exc.value.status_code == 503
    assert exc.value.detail["error"] == "postgres_not_configured"


def test_dry_run_without_dsn_skips_postgres_and_injects_anonymous(monkeypatch) -> None:
    monkeypatch.delenv("SEED_SAGA_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    called = {"db_connect": False, "user_id": None}

    async def _should_not_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        called["db_connect"] = True
        raise AssertionError("AsyncPGDatabase.get_shared must not be called in dry-run without DSN")

    async def _fake_run(self, saga_id: str, payload: dict[str, Any], steps: list[dict[str, Any]], **kwargs):  # type: ignore[no-untyped-def]
        called["user_id"] = payload.get("user_id")
        return {"status": "succeeded", "execution_trace": []}

    monkeypatch.setattr("app.api.saga_blueprints.AsyncPGDatabase.get_shared", _should_not_connect)
    monkeypatch.setattr("app.api.saga_blueprints.DynamicSaga.run", _fake_run)

    result = asyncio.run(
        _run_saga(
            {"steps": []},
            {},
            build_default_registry(),
            execution_mode=ExecutionMode.DRY_RUN,
        )
    )
    assert called["db_connect"] is False
    assert called["user_id"] == "anonymous"
    assert result["status"] == "succeeded"


def test_dry_run_injects_actor_user_id(monkeypatch) -> None:
    monkeypatch.delenv("SEED_SAGA_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    called = {"user_id": None}

    async def _fake_run(self, saga_id: str, payload: dict[str, Any], steps: list[dict[str, Any]], **kwargs):  # type: ignore[no-untyped-def]
        called["user_id"] = payload.get("user_id")
        return {"status": "succeeded", "execution_trace": []}

    monkeypatch.setattr("app.api.saga_blueprints.DynamicSaga.run", _fake_run)

    asyncio.run(
        _run_saga(
            {"steps": []},
            {},
            build_default_registry(),
            execution_mode=ExecutionMode.DRY_RUN,
            actor_user_id="ctx-user",
        )
    )
    assert called["user_id"] == "ctx-user"


def test_dry_run_avoids_real_job_scanner(monkeypatch) -> None:
    monkeypatch.delenv("SEED_SAGA_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def _boom_scanner(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("JobScanner must not be used in DRY_RUN safe mode")

    async def _fake_run(self, saga_id: str, payload: dict[str, Any], steps: list[dict[str, Any]], **kwargs):  # type: ignore[no-untyped-def]
        return {"status": "succeeded", "execution_trace": []}

    monkeypatch.setattr("app.api.saga_blueprints.JobScanner", _boom_scanner)
    monkeypatch.setattr("app.api.saga_blueprints.DynamicSaga.run", _fake_run)

    result = asyncio.run(
        _run_saga(
            {"steps": []},
            {"user_id": "u1"},
            build_default_registry(),
            execution_mode=ExecutionMode.DRY_RUN,
        )
    )
    assert result["status"] == "succeeded"
