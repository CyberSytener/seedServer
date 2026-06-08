from __future__ import annotations

from pathlib import Path

import pytest

from app.dynamic_registry import loader
from scripts import run_portfolio_demo as demo


def test_node_runtime_preflight_rejects_old_node(monkeypatch, capsys) -> None:
    monkeypatch.setattr(demo, "_command", lambda name: f"/bin/{name}")
    monkeypatch.setattr(demo.subprocess, "check_output", lambda *_args, **_kwargs: "v16.20.0\n")

    assert demo._check_node_runtime() is False
    assert "Node.js 18+ is required" in capsys.readouterr().out


def test_reset_demo_state_removes_sqlite_sidecars(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "demo.sqlite3"
    monkeypatch.setattr(demo, "DEMO_DB", database)
    paths = [database, Path(f"{database}-shm"), Path(f"{database}-wal")]
    for path in paths:
        path.write_text("state", encoding="utf-8")

    demo._reset_demo_state()

    assert all(not path.exists() for path in paths)


def test_windows_terminate_waits_for_child_process(monkeypatch) -> None:
    class Process:
        pid = 123

        def __init__(self) -> None:
            self.waited = False

        def poll(self):
            return None

        def wait(self, *, timeout: int):
            self.waited = True

    process = Process()
    monkeypatch.setattr(demo.os, "name", "nt")
    monkeypatch.setattr(demo.subprocess, "run", lambda *_args, **_kwargs: None)

    demo._terminate([process])

    assert process.waited is True


def test_smoke_checks_require_flow_and_module_history(monkeypatch) -> None:
    def request_json(method: str, url: str, **_kwargs):
        if url.endswith("/v1/me"):
            return {"user_id": "devuser"}
        if url.endswith("/sandbox"):
            return {"status": "SANDBOXED"}
        if method == "POST" and url.endswith("/v1/runs"):
            return {"status": "done"}
        if method == "GET" and url.endswith("/v1/runs"):
            return {
                "runs": [
                    {"target_type": "flow", "target_id": demo.DEMO_FLOW["flow_id"]},
                    {"target_type": "module", "target_id": "general_assistant"},
                ]
            }
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(demo, "_request_json", request_json)

    demo._run_smoke_checks("http://demo")


def test_smoke_checks_reject_history_without_module_run(monkeypatch) -> None:
    def request_json(method: str, url: str, **_kwargs):
        if url.endswith("/v1/me"):
            return {"user_id": "devuser"}
        if url.endswith("/sandbox"):
            return {"status": "SANDBOXED"}
        if method == "POST" and url.endswith("/v1/runs"):
            return {"status": "done"}
        if method == "GET" and url.endswith("/v1/runs"):
            return {"runs": [{"target_type": "flow", "target_id": demo.DEMO_FLOW["flow_id"]}]}
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(demo, "_request_json", request_json)

    with pytest.raises(RuntimeError, match="module stub run"):
        demo._run_smoke_checks("http://demo")


def test_dynamic_registry_skips_its_service_modules(tmp_path: Path, monkeypatch) -> None:
    for name in ("__init__.py", "loader.py", "portfolio_block.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(loader, "ensure_registry_dir", lambda: tmp_path)

    assert [path.name for path in loader.iter_block_files()] == ["portfolio_block.py"]
