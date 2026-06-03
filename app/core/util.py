from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_day_key(dt: datetime | None = None) -> str:
    d = (dt or utc_now()).date()
    return d.isoformat()  # YYYY-MM-DD


def utc_month_key(dt: datetime | None = None) -> str:
    d = (dt or utc_now()).date()
    return f"{d.year:04d}-{d.month:02d}-01"


def utc_minute_key(dt: datetime | None = None) -> str:
    t = (dt or utc_now()).replace(second=0, microsecond=0)
    return t.isoformat().replace('+00:00', 'Z')


def sha256_text(text: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def normalize_input(text: str) -> str:
    # minimal normalization for dedupe / hashing
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def job_id(prefix: str = "job") -> str:
    # URL-safe, reasonably short
    return f"{prefix}_{secrets.token_urlsafe(10)}"


def ns_key(namespace: str, *parts: str) -> str:
    clean = [p.replace(":", "_") for p in parts if p is not None]
    return f"{namespace}:" + ":".join(clean)
