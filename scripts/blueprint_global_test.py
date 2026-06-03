#!/usr/bin/env python3
"""
blueprint_global_test.py
-----------------------
Global blueprint drafting test across multiple prompts and model tiers.

Reads admin JWT from SAGA_ADMIN_JWT env var.

Usage:
  python scripts/blueprint_global_test.py --base-url http://localhost:8000

Optional:
  --tiers cheap,balanced,powerful
  --prompts "..." "..." "..."
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from typing import Any, Dict, List

DEFAULT_PROMPTS = [
    "Create a saga that scans jobs and scores them for a backend engineer persona.",
    "Build a workflow that scans jobs, scores them, and sends a top 3 notification.",
    "Create a nested saga that runs standard_job_alert and then logs a summary step.",
]

DEFAULT_TIERS = ["cheap", "balanced", "powerful"]


def request_json(
    url: str,
    method: str = "GET",
    data: Dict[str, Any] | None = None,
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    payload = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"{exc.code} {exc.reason}: {body[:500]}") from exc


def summarize(result: Dict[str, Any]) -> Dict[str, Any]:
    model = result.get("model") or {}
    safety = result.get("safety") or {}
    dry = result.get("dry_run") or {}
    return {
        "ok": result.get("ok"),
        "status": result.get("status"),
        "model_name": model.get("model_name"),
        "model_tier": model.get("model_tier"),
        "validation_errors": len(result.get("validation_errors") or []),
        "safety_passed": safety.get("passed"),
        "dry_run_status": dry.get("status"),
        "job_count": dry.get("job_count"),
        "scored_count": dry.get("scored_count"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Global blueprint drafting test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--tiers", default=",".join(DEFAULT_TIERS))
    parser.add_argument("--prompts", nargs="*", default=DEFAULT_PROMPTS)
    args = parser.parse_args()

    token = os.getenv("SAGA_ADMIN_JWT", "")
    if not token:
        print("ERROR: SAGA_ADMIN_JWT is required for admin endpoints.")
        return 1

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    prompts: List[str] = args.prompts

    headers = {"Authorization": f"Bearer {token}"}

    print("Seeding gallery...")
    request_json(f"{args.base_url}/v1/sagas/blueprints/gallery/seed", method="POST", headers=headers)

    results: Dict[str, Dict[str, Any]] = {}

    for prompt in prompts:
        print("\nPrompt:")
        print(f"  {prompt}")
        for tier in tiers:
            body = {"prompt": prompt, "model_tier": tier, "owner_id": f"test-{tier}"}
            key = f"{prompt}__{tier}"
            try:
                res = request_json(
                    f"{args.base_url}/v1/sagas/architect/draft",
                    method="POST",
                    data=body,
                    headers=headers,
                )
                results[key] = res
                summary = summarize(res)
                print(
                    f"  - {tier:9s} ok={summary['ok']} status={summary['status']} "
                    f"model={summary['model_name']} safety={summary['safety_passed']} "
                    f"dry_run={summary['dry_run_status']} errors={summary['validation_errors']}"
                )
            except Exception as exc:
                print(f"  - {tier:9s} ERROR: {exc}")

    print("\nDetailed summary:")
    for key, res in results.items():
        summary = summarize(res)
        print(f"\n[{key}]")
        print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
