from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INTEL_PATH = ROOT / "archive" / "data" / "server_intel.json"
SNAPSHOT_PATH = ROOT / "archive" / "data" / "server_intel.snapshot.json"


ROUTE_DECORATOR_RE = re.compile(
    r"@(?:app|router)\.(?:get|post|put|patch|delete|options|head)\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)


@dataclass
class DriftResult:
    missing_files: list[str]
    missing_routes: list[str]
    unresolved_file_refs: list[str]

    @property
    def total(self) -> int:
        return len(self.missing_files) + len(self.missing_routes) + len(self.unresolved_file_refs)


def _iter_json_values(obj: Any):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key, value
            yield from _iter_json_values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield None, value
            yield from _iter_json_values(value)


def _collect_claimed_files(intel: dict[str, Any]) -> list[str]:
    files: set[str] = set()
    for key, value in _iter_json_values(intel):
        if key == "file" and isinstance(value, str):
            raw = value.strip().replace("\\", "/")
            if raw:
                files.add(raw)
    return sorted(files)


def _collect_claimed_routes(intel: dict[str, Any]) -> list[str]:
    routes: set[str] = set()
    for key, value in _iter_json_values(intel):
        if key == "url" and isinstance(value, str):
            route = value.strip()
            if route.startswith("/"):
                routes.add(route)
    return sorted(routes)


def _collect_source_routes(root: Path) -> set[str]:
    routes: set[str] = set()
    for py in (root / "app").rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except Exception:
            continue
        for match in ROUTE_DECORATOR_RE.finditer(text):
            routes.add(match.group(1).strip())
    return routes


def _resolve_file_claim(path_str: str) -> tuple[bool, str]:
    normalized = path_str.replace("\\", "/")
    if not normalized:
        return False, ""
    if normalized.startswith("/"):
        normalized = normalized[1:]
    candidate = ROOT / normalized
    if candidate.exists():
        return True, normalized

    if normalized.startswith("app/"):
        return False, normalized

    app_candidate = ROOT / "app" / normalized
    if app_candidate.exists():
        return True, f"app/{normalized}"

    return False, normalized


def run_check(max_drift: int, write_snapshot: bool = False) -> DriftResult:
    intel = json.loads(INTEL_PATH.read_text(encoding="utf-8"))

    claimed_files = _collect_claimed_files(intel)
    claimed_routes = _collect_claimed_routes(intel)
    source_routes = _collect_source_routes(ROOT)

    missing_files: list[str] = []
    unresolved_file_refs: list[str] = []
    for claimed in claimed_files:
        exists, resolved = _resolve_file_claim(claimed)
        if not exists:
            missing_files.append(claimed)
        elif resolved != claimed:
            unresolved_file_refs.append(f"{claimed} -> {resolved}")

    missing_routes = [route for route in claimed_routes if route not in source_routes]

    result = DriftResult(
        missing_files=sorted(set(missing_files)),
        missing_routes=sorted(set(missing_routes)),
        unresolved_file_refs=sorted(set(unresolved_file_refs)),
    )

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": os.getenv("GITHUB_SHA", "local"),
        "intel_path": str(INTEL_PATH.relative_to(ROOT)).replace("\\", "/"),
        "drift": {
            "missing_files": result.missing_files,
            "missing_routes": result.missing_routes,
            "unresolved_file_refs": result.unresolved_file_refs,
            "total": result.total,
            "max_allowed": max_drift,
        },
    }

    if write_snapshot:
        SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(snapshot, ensure_ascii=False, indent=2))

    if result.total > max_drift:
        return result
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate drift between server_intel.json claims and source code.")
    parser.add_argument("--max-drift", type=int, default=int(os.getenv("SERVER_INTEL_DRIFT_MAX", "0")))
    parser.add_argument("--write-snapshot", action="store_true")
    args = parser.parse_args()

    if not INTEL_PATH.exists():
        print(f"server_intel not found: {INTEL_PATH}", file=sys.stderr)
        return 2

    result = run_check(max_drift=args.max_drift, write_snapshot=args.write_snapshot)
    if result.total > args.max_drift:
        print(
            f"Drift check failed: total={result.total} > max_allowed={args.max_drift}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
