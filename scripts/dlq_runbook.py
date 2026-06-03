import argparse
import json
import urllib.request
from typing import Any, Dict


def _request_json(method: str, url: str, admin_key: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = None
    headers = {
        "X-Admin-Key": admin_key,
        "Content-Type": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, method=method, headers=headers, data=data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="DLQ runbook helper for Seed Saga health API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--admin-key", required=True, help="SEED admin key")

    sub = parser.add_subparsers(dest="command", required=True)

    cmd_candidates = sub.add_parser("retry-candidates", help="List retry candidates")
    cmd_candidates.add_argument("--limit", type=int, default=100)

    cmd_auto = sub.add_parser("auto-triage", help="Run auto triage policy")
    cmd_auto.add_argument("--limit", type=int, default=200)
    cmd_auto.add_argument("--retry-count-threshold", type=int, default=2)
    cmd_auto.add_argument("--min-age-minutes", type=int, default=10)
    cmd_auto.add_argument("--retry-delay-seconds", type=int, default=300)
    cmd_auto.add_argument("--triage-status", default="queued_for_retry")
    cmd_auto.add_argument("--note", default="cli runbook")
    cmd_auto.add_argument("--types", nargs="*", default=[])
    cmd_auto.add_argument("--apply", action="store_true", help="Apply updates (otherwise dry-run)")

    cmd_purge = sub.add_parser("purge", help="Purge old DLQ rows")
    cmd_purge.add_argument("--older-than-days", type=int, default=30)
    cmd_purge.add_argument("--limit", type=int, default=1000)

    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    if args.command == "retry-candidates":
        url = f"{base}/api/v1/health/saga/dlq/retry-candidates?limit={int(args.limit)}"
        result = _request_json("GET", url, args.admin_key)
    elif args.command == "auto-triage":
        url = f"{base}/api/v1/health/saga/dlq/auto-triage"
        payload: Dict[str, Any] = {
            "limit": int(args.limit),
            "retry_count_threshold": int(args.retry_count_threshold),
            "min_age_minutes": int(args.min_age_minutes),
            "dry_run": not bool(args.apply),
            "retry_delay_seconds": int(args.retry_delay_seconds),
            "triage_status": str(args.triage_status),
            "note": str(args.note),
        }
        if args.types:
            payload["include_message_types"] = [str(t) for t in args.types]
        result = _request_json("POST", url, args.admin_key, payload)
    else:
        url = f"{base}/api/v1/health/saga/dlq/purge"
        payload = {
            "older_than_days": int(args.older_than_days),
            "limit": int(args.limit),
        }
        result = _request_json("POST", url, args.admin_key, payload)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
