from __future__ import annotations

import os

from app.infrastructure.db.sqlite import DB, seed_defaults
from app.settings import get_settings


def main() -> None:
    s = get_settings()
    db_path = os.getenv("SEED_DB_PATH", s.db_path)
    db = DB(db_path)
    db.init_schema()
    seed_defaults(db)
    db.close()
    print(f"ok: {db_path}")


if __name__ == "__main__":
    main()

