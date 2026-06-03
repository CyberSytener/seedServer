from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _build_url(base_url: str, params: dict[str, str]) -> str:
    clean_base = base_url.rstrip("/")
    query = urllib.parse.urlencode(params)
    return f"{clean_base}/api/v1/neoeats/memory/embeddings/admin/backfill?{query}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NeoEats RAG embedding backfill via the admin API.")
    parser.add_argument("--base-url", default=os.getenv("NEOEATS_API_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--admin-key", default=os.getenv("SEED_ADMIN_KEY", ""))
    parser.add_argument("--limit-per-user", type=int, default=int(os.getenv("NEOEATS_EMBEDDING_BACKFILL_LIMIT_PER_USER", "50")))
    parser.add_argument("--max-users", type=int, default=int(os.getenv("NEOEATS_EMBEDDING_BACKFILL_MAX_USERS", "25")))
    parser.add_argument("--statuses", default=os.getenv("NEOEATS_EMBEDDING_BACKFILL_STATUSES", "pending,failed,unavailable"))
    parser.add_argument("--dry-run", action="store_true", default=os.getenv("NEOEATS_EMBEDDING_BACKFILL_DRY_RUN", "").lower() in {"1", "true", "yes"})
    args = parser.parse_args()

    if not args.admin_key:
        print(json.dumps({"ok": False, "error": "missing_admin_key"}, indent=2))
        return 2

    url = _build_url(
        args.base_url,
        {
            "limit_per_user": str(args.limit_per_user),
            "max_users": str(args.max_users),
            "statuses": args.statuses,
            "dry_run": "true" if args.dry_run else "false",
        },
    )
    request = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Admin-Key": args.admin_key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"ok": False, "status": exc.code, "error": body}, indent=2))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
