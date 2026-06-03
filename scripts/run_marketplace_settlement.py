from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from app.infrastructure.db.sqlite import DB
from app.services.marketplace import MarketplaceService


def _default_run_id() -> str:
    return "settlement_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run marketplace settlement and payout ledger generation.")
    parser.add_argument("--db-path", default=os.getenv("SEED_DB_PATH", "./seed.db"))
    parser.add_argument("--run-id", default=_default_run_id())
    parser.add_argument("--mode-id", default=None)
    args = parser.parse_args()

    db = DB(args.db_path)
    db.init_schema()
    service = MarketplaceService(db)
    result = service.run_settlement(run_id=args.run_id, mode_id=args.mode_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
