"""
Seed demo blueprints for local development.

Polls /health until the API is ready, then calls
POST /blueprints/gallery/seed to populate the Saga Console gallery
with sample workflows that work in stub mode (no API keys required).

Usage:
    python scripts/seed_demo.py
    python scripts/seed_demo.py --url http://localhost:8000 --key my-admin-key
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:8000"
DEFAULT_ADMIN_KEY = "dev-only-change-before-deploy"
HEALTH_TIMEOUT = 60   # seconds to wait for API to be healthy
HEALTH_INTERVAL = 2   # seconds between health-check attempts


def wait_for_health(base_url: str) -> bool:
    """Poll /health until the API responds 200 or the timeout is reached."""
    url = f"{base_url}/health"
    deadline = time.monotonic() + HEALTH_TIMEOUT
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    print(f"  API healthy (attempt {attempt}).")
                    return True
        except Exception:
            pass
        print(f"  Waiting for API ({attempt})...", end="\r", flush=True)
        time.sleep(HEALTH_INTERVAL)
    print()
    return False


def seed_gallery(base_url: str, admin_key: str) -> list[str]:
    """POST /v1/sagas/blueprints/gallery/seed and return the list of seeded names."""
    url = f"{base_url}/v1/sagas/blueprints/gallery/seed"
    req = urllib.request.Request(url, method="POST")
    req.add_header("X-Admin-Key", admin_key)
    req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data.get("seeded", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Saga Console demo blueprints")
    parser.add_argument("--url", default=DEFAULT_URL, help="API base URL")
    parser.add_argument("--key", default=DEFAULT_ADMIN_KEY, help="Admin key (X-Admin-Key header)")
    args = parser.parse_args()

    print(f"\nSeed Demo  —  {args.url}")
    print("─" * 44)

    print("1. Waiting for API to be healthy...")
    if not wait_for_health(args.url):
        print(f"   ERROR: API did not become healthy within {HEALTH_TIMEOUT}s.")
        print("   Make sure the stack is running: make dev-detach")
        return 1

    print("2. Seeding gallery blueprints...")
    try:
        names = seed_gallery(args.url, args.key)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("   AUTH ERROR: wrong admin key.")
            print("   Check SEED_ADMIN_KEY in docker-compose.dev.yml and pass --key.")
        else:
            print(f"   HTTP {exc.code}: {exc.reason}")
        return 1
    except Exception as exc:
        print(f"   ERROR: {exc}")
        return 1

    if names:
        print(f"   Seeded {len(names)} blueprint(s):")
        for name in names:
            print(f"     • {name}")
    else:
        print("   Already seeded (or no blueprints defined in gallery).")

    print()
    print("─" * 44)
    print("Done. Open the Saga Console:")
    print("  URL:      http://localhost:5173")
    print("  Username: L0g1n")
    print("  Password: P@SSW0RD")
    print("─" * 44)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
