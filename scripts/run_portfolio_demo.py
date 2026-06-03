"""Run the Seed Server portfolio demo locally.

This launcher is intentionally small and dependency-light: it uses only the
Python standard library, starts the FastAPI backend in deterministic stub mode,
starts the React Saga Console, seeds one gallery flow, and prints the reviewer
credentials.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONSOLE_DIR = ROOT / "saga-console"
DEMO_DIR = ROOT / ".demo"
DEMO_DB = DEMO_DIR / "seed_demo.sqlite3"
BACKEND_READY_TIMEOUT = 75
FRONTEND_READY_TIMEOUT = 75
DEMO_TOKEN = (
    "test_devuser|developer|"
    "runs:read,runs:write,modules:read,modules:write,flows:read,flows:write,"
    "catalog:read,blueprints:write,providers:read,providers:use:real"
)

DEMO_FLOW = {
    "flow_id": "market_scan_default",
    "version": "v1",
    "blueprint": {
        "steps": [
            {
                "id": "market_scanner_1",
                "block": "market_scanner",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "persona": {"from": "persona"},
                },
            },
            {
                "id": "job_scorer_1",
                "block": "job_scorer",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "persona": {"from": "persona"},
                    "jobs": {"from": "market_scanner_1.jobs"},
                    "scan_id": {"from": "market_scanner_1.scan_id"},
                },
            },
            {
                "id": "notification_1",
                "block": "notification_block",
                "inputs": {"items": {"from": "job_scorer_1.scored_jobs"}},
                "params": {"channel": "webhook", "top_n": 3},
            },
        ]
    },
    "save": True,
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def _command(name: str) -> str | None:
    if os.name == "nt" and name == "npm":
        return shutil.which("npm.cmd") or shutil.which("npm")
    return shutil.which(name)


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _choose_port(preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        if _port_available(port):
            return port
    raise RuntimeError(f"No free localhost port found near {preferred}")


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = DEMO_TOKEN,
    timeout: int = 10,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _wait_for_json(url: str, *, token: str | None, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _request_json("GET", url, token=token, timeout=5)
            return True
        except Exception:
            time.sleep(1)
    return False


def _wait_for_http(url: str, *, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if 200 <= resp.status < 500:
                    return True
        except Exception:
            time.sleep(1)
    return False


def _check_python_deps() -> bool:
    missing = [
        package
        for package in ("fastapi", "uvicorn", "pydantic")
        if importlib.util.find_spec(package) is None
    ]
    if not missing:
        return True

    print("Missing Python dependencies:", ", ".join(missing))
    print('Install them first: python -m pip install -e ".[dev]"')
    return False


def _ensure_frontend_deps(skip_install: bool) -> bool:
    package_json = CONSOLE_DIR / "package.json"
    node_modules = CONSOLE_DIR / "node_modules"
    npm = _command("npm")
    if not package_json.exists():
        print("Saga Console package.json not found.")
        return False
    if node_modules.exists() or skip_install:
        return True
    if not npm:
        print("npm is not available. Install Node.js 18+ and rerun the demo.")
        return False

    print("Installing Saga Console dependencies with npm install...")
    subprocess.check_call([npm, "install"], cwd=CONSOLE_DIR)
    return True


def _demo_env(backend_port: int) -> tuple[dict[str, str], dict[str, str]]:
    DEMO_DIR.mkdir(exist_ok=True)
    backend_env = os.environ.copy()
    backend_env.update(
        {
            "SEED_ENV": "test",
            "SEED_TEST_AUTH_MODE": "1",
            "SEED_DEV_CORS": "1",
            "SEED_ENABLE_STUB": "1",
            "SEED_DEFAULT_PROVIDER_FAST": "stub",
            "SEED_DEFAULT_PROVIDER_BATCH": "stub",
            "SEED_METRICS_ENABLED": "0",
            "SEED_LOG_LEVEL": "WARNING",
            "SEED_ADMIN_KEY": "portfolio_demo_admin",
            "SEED_API_KEY_PEPPER": "portfolio_demo_pepper",
            "SEED_DB_PATH": str(DEMO_DB),
            "PYTHONUNBUFFERED": "1",
        }
    )

    frontend_env = os.environ.copy()
    frontend_env["VITE_API_BASE_URL"] = f"http://127.0.0.1:{backend_port}"
    return backend_env, frontend_env


def _stream_target(verbose: bool) -> int | None:
    return None if verbose else subprocess.DEVNULL


def _start_backend(port: int, env: dict[str, str], *, verbose: bool) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        cwd=ROOT,
        env=env,
        stdout=_stream_target(verbose),
        stderr=_stream_target(verbose),
    )


def _start_frontend(port: int, env: dict[str, str], *, verbose: bool) -> subprocess.Popen[Any]:
    npm = _command("npm")
    if not npm:
        raise RuntimeError("npm is not available")
    return subprocess.Popen(
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=CONSOLE_DIR,
        env=env,
        stdout=_stream_target(verbose),
        stderr=_stream_target(verbose),
    )


def _terminate(processes: list[subprocess.Popen[Any]]) -> None:
    if os.name == "nt":
        for proc in processes:
            if proc.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
        return

    for proc in processes:
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
    deadline = time.monotonic() + 8
    for proc in processes:
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass


def _seed_demo_flow(api_base: str) -> None:
    _request_json("POST", f"{api_base}/v1/flows/compile", payload=DEMO_FLOW)
    flow = _request_json("GET", f"{api_base}/v1/flows/{DEMO_FLOW['flow_id']}")
    nodes = flow.get("nodes") if isinstance(flow, dict) else []
    if not isinstance(nodes, list) or not nodes:
        raise RuntimeError("Demo flow was not persisted correctly")


def _run_smoke_checks(api_base: str) -> None:
    me = _request_json("GET", f"{api_base}/v1/me")
    if me.get("user_id") != "devuser":
        raise RuntimeError("/v1/me did not accept the demo token")

    sandbox = _request_json("POST", f"{api_base}/v1/flows/{DEMO_FLOW['flow_id']}/sandbox")
    if sandbox.get("status") != "SANDBOXED":
        raise RuntimeError("Sandbox endpoint did not mark the demo flow as SANDBOXED")

    run = _request_json(
        "POST",
        f"{api_base}/v1/runs",
        payload={
            "target": {"type": "module", "id": "general_assistant"},
            "mode": "stub",
            "input": {"user_request": "Portfolio smoke test"},
        },
    )
    if run.get("status") != "done":
        raise RuntimeError("Module stub run did not complete")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Seed Server portfolio demo")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--skip-install", action="store_true", help="Do not run npm install if node_modules is missing")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    parser.add_argument("--smoke-test", action="store_true", help="Start services, run checks, stop, and exit")
    parser.add_argument("--verbose", action="store_true", help="Show uvicorn and Vite logs")
    args = parser.parse_args()

    if not _check_python_deps():
        return 1
    if not _ensure_frontend_deps(args.skip_install):
        return 1

    backend_port = _choose_port(args.backend_port)
    frontend_port = _choose_port(args.frontend_port)
    api_base = f"http://127.0.0.1:{backend_port}"
    console_url = f"http://127.0.0.1:{frontend_port}/gallery"
    backend_env, frontend_env = _demo_env(backend_port)
    processes: list[subprocess.Popen[Any]] = []

    print()
    print("Seed Server Portfolio Demo")
    print("=" * 34)
    print(f"Backend:      {api_base}")
    print(f"Saga Console: {console_url}")
    print("Login:        L0g1n / P@SSW0RD")
    print()

    try:
        print("Starting backend...")
        backend = _start_backend(backend_port, backend_env, verbose=args.verbose)
        processes.append(backend)
        if not _wait_for_json(f"{api_base}/v1/modules", token=DEMO_TOKEN, timeout=BACKEND_READY_TIMEOUT):
            print("Backend did not become ready. Check the logs above.")
            return 1

        print("Seeding demo flow...")
        _seed_demo_flow(api_base)

        print("Starting Saga Console...")
        frontend = _start_frontend(frontend_port, frontend_env, verbose=args.verbose)
        processes.append(frontend)
        if not _wait_for_http(console_url, timeout=FRONTEND_READY_TIMEOUT):
            print("Saga Console did not become ready. Check the logs above.")
            return 1

        if args.smoke_test:
            print("Running smoke checks...")
            _run_smoke_checks(api_base)
            print("Smoke test passed.")
            return 0

        print()
        print("Demo is ready.")
        print(f"Open: {console_url}")
        print("Credentials: L0g1n / P@SSW0RD")
        print()
        print("Suggested 3-minute review path:")
        print("  1. Gallery -> open market_scan_default")
        print("  2. Canvas -> inspect modules and edges")
        print("  3. Gallery -> Sandbox")
        print("  4. Modules -> run general_assistant in stub mode")
        print("  5. Runs -> inspect the timeline")
        print()
        print("Press Ctrl+C to stop the demo.")
        if not args.no_open:
            webbrowser.open(console_url)

        while all(proc.poll() is None for proc in processes):
            time.sleep(1)
        return 0
    except KeyboardInterrupt:
        print("\nStopping demo...")
        return 0
    except urllib.error.HTTPError as exc:
        print(f"HTTP error during demo startup: {exc.code} {exc.reason}")
        return 1
    except Exception as exc:
        print(f"Demo startup failed: {exc}")
        return 1
    finally:
        if args.smoke_test:
            _terminate(processes)
        else:
            _terminate(processes)


if __name__ == "__main__":
    if os.name != "nt":
        signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    raise SystemExit(main())
