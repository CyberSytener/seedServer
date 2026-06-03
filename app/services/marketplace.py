from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from app.infrastructure.db.sqlite import DB

VISIBILITY_VALUES = {"public", "private"}
STATUS_VALUES = {"active", "disabled", "archived"}


def _parse_json(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _to_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        out.append(normalized)
        seen.add(normalized)
    return out


def _normalize_sandbox_policy(policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = policy if isinstance(policy, dict) else {}

    allowed = _string_list(payload.get("allowed_capabilities"))
    blocked = _string_list(payload.get("blocked_capabilities"))

    min_reputation = payload.get("min_reputation_score", 0.0)
    try:
        min_reputation_value = float(min_reputation)
    except (TypeError, ValueError):
        min_reputation_value = 0.0
    min_reputation_value = max(0.0, min(1.0, min_reputation_value))

    return {
        "allowed_capabilities": allowed,
        "blocked_capabilities": blocked,
        "min_reputation_score": round(min_reputation_value, 4),
    }


def _normalize_billing_policy(policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = policy if isinstance(policy, dict) else {}

    creator_share = payload.get("revenue_share_creator_pct", 0.7)
    try:
        creator_share_value = float(creator_share)
    except (TypeError, ValueError):
        creator_share_value = 0.7
    creator_share_value = max(0.0, min(1.0, creator_share_value))

    settlement_days = payload.get("settlement_window_days", 30)
    try:
        settlement_days_value = int(settlement_days)
    except (TypeError, ValueError):
        settlement_days_value = 30
    settlement_days_value = max(1, min(365, settlement_days_value))

    minimum_payout_credits = payload.get("minimum_payout_credits", 100.0)
    try:
        minimum_payout_credits_value = float(minimum_payout_credits)
    except (TypeError, ValueError):
        minimum_payout_credits_value = 100.0
    minimum_payout_credits_value = max(0.0, minimum_payout_credits_value)

    monetization_enabled = bool(payload.get("monetization_enabled", True))
    currency = str(payload.get("currency") or "credits").strip().lower() or "credits"

    return {
        "revenue_share_creator_pct": round(creator_share_value, 6),
        "revenue_share_platform_pct": round(1.0 - creator_share_value, 6),
        "settlement_window_days": settlement_days_value,
        "minimum_payout_credits": round(minimum_payout_credits_value, 6),
        "monetization_enabled": monetization_enabled,
        "currency": currency,
    }


def ensure_marketplace_tables(db: DB) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_modules (
            mode_id TEXT PRIMARY KEY,
            display_name TEXT,
            description TEXT,
            owner_tenant_id TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            status TEXT NOT NULL DEFAULT 'active',
            sandbox_policy_json TEXT NOT NULL DEFAULT '{}',
            billing_policy_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            review TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(mode_id, user_id),
            FOREIGN KEY(mode_id) REFERENCES marketplace_modules(mode_id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode_id TEXT NOT NULL,
            consumer_user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            credits REAL NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0,
            gross_credits REAL NOT NULL DEFAULT 0,
            creator_share_credits REAL NOT NULL DEFAULT 0,
            platform_share_credits REAL NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(mode_id) REFERENCES marketplace_modules(mode_id) ON DELETE CASCADE
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_payout_ledger (
            payout_id TEXT PRIMARY KEY,
            mode_id TEXT NOT NULL,
            owner_tenant_id TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL DEFAULT 'credits',
            settlement_window_days INTEGER NOT NULL DEFAULT 30,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            event_count INTEGER NOT NULL DEFAULT 0,
            gross_credits REAL NOT NULL DEFAULT 0,
            creator_share_credits REAL NOT NULL DEFAULT 0,
            platform_share_credits REAL NOT NULL DEFAULT 0,
            minimum_payout_credits REAL NOT NULL DEFAULT 0,
            payout_eligible INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            run_id TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(mode_id, window_start, window_end),
            FOREIGN KEY(mode_id) REFERENCES marketplace_modules(mode_id) ON DELETE CASCADE
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_modules_visibility ON marketplace_modules(visibility, status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_usage_mode ON marketplace_usage_events(mode_id, created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_ratings_mode ON marketplace_ratings(mode_id, created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_payout_mode ON marketplace_payout_ledger(mode_id, created_at)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_marketplace_payout_owner ON marketplace_payout_ledger(owner_tenant_id, created_at)")


class MarketplaceService:
    def __init__(self, db: DB) -> None:
        self._db = db
        ensure_marketplace_tables(self._db)

    def _listing_from_row(self, row: Any) -> Dict[str, Any]:
        listing = {
            "mode_id": str(row["mode_id"]),
            "display_name": str(row["display_name"] or row["mode_id"]),
            "description": str(row["description"] or ""),
            "owner_tenant_id": str(row["owner_tenant_id"] or ""),
            "visibility": str(row["visibility"] or "private"),
            "status": str(row["status"] or "active"),
            "sandbox_policy": _parse_json(row["sandbox_policy_json"]),
            "billing_policy": _parse_json(row["billing_policy_json"]),
            "metadata": _parse_json(row["metadata_json"]),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }
        listing["reputation"] = self.get_reputation(listing["mode_id"])
        return listing

    def get_listing(self, *, mode_id: str, include_private: bool = True) -> Optional[Dict[str, Any]]:
        normalized_mode_id = str(mode_id or "").strip()
        if not normalized_mode_id:
            return None
        row = self._db.fetchone(
            """
            SELECT mode_id, display_name, description, owner_tenant_id, visibility, status,
                   sandbox_policy_json, billing_policy_json, metadata_json, created_at, updated_at
            FROM marketplace_modules
            WHERE mode_id = ?
            """,
            (normalized_mode_id,),
        )
        if row is None:
            return None
        listing = self._listing_from_row(row)
        if not include_private and listing["visibility"] != "public":
            return None
        return listing

    def list_listings(
        self,
        *,
        visibility: Optional[str] = None,
        include_private: bool = False,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        if not include_inactive:
            clauses.append("status = ?")
            params.append("active")

        normalized_visibility = str(visibility or "").strip().lower()
        if normalized_visibility:
            if normalized_visibility not in VISIBILITY_VALUES:
                raise ValueError(f"unsupported_visibility:{normalized_visibility}")
            clauses.append("visibility = ?")
            params.append(normalized_visibility)
        elif not include_private:
            clauses.append("visibility = ?")
            params.append("public")

        where_sql = ""
        if clauses:
            where_sql = "WHERE " + " AND ".join(clauses)

        rows = self._db.fetchall(
            f"""
            SELECT mode_id, display_name, description, owner_tenant_id, visibility, status,
                   sandbox_policy_json, billing_policy_json, metadata_json, created_at, updated_at
            FROM marketplace_modules
            {where_sql}
            ORDER BY mode_id ASC
            """,
            tuple(params),
        )
        return [self._listing_from_row(row) for row in rows]

    def upsert_listing(
        self,
        *,
        mode_id: str,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        owner_tenant_id: Optional[str] = None,
        visibility: str = "private",
        status: str = "active",
        sandbox_policy: Optional[Dict[str, Any]] = None,
        billing_policy: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_mode_id = str(mode_id or "").strip()
        if not normalized_mode_id:
            raise ValueError("mode_id is required")

        normalized_visibility = str(visibility or "").strip().lower() or "private"
        if normalized_visibility not in VISIBILITY_VALUES:
            raise ValueError(f"unsupported_visibility:{normalized_visibility}")

        normalized_status = str(status or "").strip().lower() or "active"
        if normalized_status not in STATUS_VALUES:
            raise ValueError(f"unsupported_status:{normalized_status}")

        safe_metadata = metadata if isinstance(metadata, dict) else {}
        safe_sandbox = _normalize_sandbox_policy(sandbox_policy)
        safe_billing = _normalize_billing_policy(billing_policy)

        resolved_display_name = str(display_name or normalized_mode_id).strip() or normalized_mode_id
        resolved_description = str(description or "").strip()
        resolved_owner_tenant_id = str(owner_tenant_id or "").strip()

        self._db.execute(
            """
            INSERT INTO marketplace_modules(
                mode_id, display_name, description, owner_tenant_id, visibility, status,
                sandbox_policy_json, billing_policy_json, metadata_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(mode_id) DO UPDATE SET
                display_name = excluded.display_name,
                description = excluded.description,
                owner_tenant_id = excluded.owner_tenant_id,
                visibility = excluded.visibility,
                status = excluded.status,
                sandbox_policy_json = excluded.sandbox_policy_json,
                billing_policy_json = excluded.billing_policy_json,
                metadata_json = excluded.metadata_json,
                updated_at = datetime('now')
            """,
            (
                normalized_mode_id,
                resolved_display_name,
                resolved_description,
                resolved_owner_tenant_id,
                normalized_visibility,
                normalized_status,
                _to_json(safe_sandbox),
                _to_json(safe_billing),
                _to_json(safe_metadata),
            ),
        )
        listing = self.get_listing(mode_id=normalized_mode_id, include_private=True)
        if listing is None:
            raise ValueError("listing_persist_failed")
        return listing

    def update_sandbox_policy(self, *, mode_id: str, sandbox_policy: Dict[str, Any]) -> Dict[str, Any]:
        listing = self.get_listing(mode_id=mode_id, include_private=True)
        if listing is None:
            raise ValueError("mode_not_found")
        normalized_policy = _normalize_sandbox_policy(sandbox_policy)
        self._db.execute(
            """
            UPDATE marketplace_modules
            SET sandbox_policy_json = ?, updated_at = datetime('now')
            WHERE mode_id = ?
            """,
            (_to_json(normalized_policy), str(mode_id).strip()),
        )
        refreshed = self.get_listing(mode_id=mode_id, include_private=True)
        if refreshed is None:
            raise ValueError("mode_not_found")
        return refreshed

    def update_billing_policy(self, *, mode_id: str, billing_policy: Dict[str, Any]) -> Dict[str, Any]:
        listing = self.get_listing(mode_id=mode_id, include_private=True)
        if listing is None:
            raise ValueError("mode_not_found")
        normalized_policy = _normalize_billing_policy(billing_policy)
        self._db.execute(
            """
            UPDATE marketplace_modules
            SET billing_policy_json = ?, updated_at = datetime('now')
            WHERE mode_id = ?
            """,
            (_to_json(normalized_policy), str(mode_id).strip()),
        )
        refreshed = self.get_listing(mode_id=mode_id, include_private=True)
        if refreshed is None:
            raise ValueError("mode_not_found")
        return refreshed

    def upsert_rating(
        self,
        *,
        mode_id: str,
        user_id: str,
        rating: int,
        review: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_mode_id = str(mode_id or "").strip()
        if not normalized_mode_id:
            raise ValueError("mode_id is required")
        if self.get_listing(mode_id=normalized_mode_id, include_private=True) is None:
            raise ValueError("mode_not_found")

        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")

        rating_value = int(rating)
        if rating_value < 1 or rating_value > 5:
            raise ValueError("rating must be between 1 and 5")

        self._db.execute(
            """
            INSERT INTO marketplace_ratings(mode_id, user_id, rating, review, created_at, updated_at)
            VALUES(?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(mode_id, user_id) DO UPDATE SET
                rating = excluded.rating,
                review = excluded.review,
                updated_at = datetime('now')
            """,
            (
                normalized_mode_id,
                normalized_user_id,
                rating_value,
                str(review or "").strip() or None,
            ),
        )
        return self.get_reputation(normalized_mode_id)

    def get_reputation(self, mode_id: str) -> Dict[str, Any]:
        normalized_mode_id = str(mode_id or "").strip()
        if not normalized_mode_id:
            return {
                "rating_count": 0,
                "average_rating": 0.0,
                "distribution": {},
                "trust_score": 0.0,
                "trust_tier": "new",
            }

        aggregate = self._db.fetchone(
            "SELECT COUNT(*) AS rating_count, COALESCE(AVG(rating), 0.0) AS average_rating FROM marketplace_ratings WHERE mode_id = ?",
            (normalized_mode_id,),
        )
        rating_count = int(aggregate["rating_count"]) if aggregate else 0
        average_rating = float(aggregate["average_rating"]) if aggregate else 0.0

        distribution_rows = self._db.fetchall(
            "SELECT rating, COUNT(*) AS count FROM marketplace_ratings WHERE mode_id = ? GROUP BY rating ORDER BY rating ASC",
            (normalized_mode_id,),
        )
        distribution = {str(int(row["rating"])): int(row["count"]) for row in distribution_rows}

        confidence = min(1.0, rating_count / 20.0)
        trust_score = round((average_rating / 5.0) * confidence, 4)
        if trust_score >= 0.8:
            trust_tier = "gold"
        elif trust_score >= 0.55:
            trust_tier = "silver"
        elif trust_score >= 0.25:
            trust_tier = "bronze"
        else:
            trust_tier = "new"

        return {
            "rating_count": rating_count,
            "average_rating": round(average_rating, 4),
            "distribution": distribution,
            "trust_score": trust_score,
            "trust_tier": trust_tier,
        }

    def validate_sandbox_request(self, *, mode_id: str, requested_capabilities: List[str]) -> List[str]:
        listing = self.get_listing(mode_id=mode_id, include_private=True)
        if listing is None:
            return []
        if listing["status"] != "active":
            return [f"marketplace_listing_inactive:{listing['status']}"]

        sandbox_policy = listing.get("sandbox_policy") if isinstance(listing.get("sandbox_policy"), dict) else {}
        allowed_capabilities = set(_string_list(sandbox_policy.get("allowed_capabilities")))
        blocked_capabilities = set(_string_list(sandbox_policy.get("blocked_capabilities")))
        requested = _string_list(requested_capabilities)

        violations: List[str] = []
        for capability in requested:
            if allowed_capabilities and capability not in allowed_capabilities:
                violations.append(f"marketplace_sandbox_capability_denied:{capability}")
            if capability in blocked_capabilities:
                violations.append(f"marketplace_sandbox_capability_blocked:{capability}")

        min_reputation_score = sandbox_policy.get("min_reputation_score", 0.0)
        try:
            min_reputation_value = float(min_reputation_score)
        except (TypeError, ValueError):
            min_reputation_value = 0.0
        min_reputation_value = max(0.0, min(1.0, min_reputation_value))
        if min_reputation_value > 0:
            reputation = self.get_reputation(str(mode_id))
            trust_score = float(reputation.get("trust_score", 0.0))
            if trust_score < min_reputation_value:
                violations.append(
                    f"marketplace_trust_score_below_min:{trust_score:.4f}<{min_reputation_value:.4f}"
                )

        return violations

    def estimate_revenue_split(self, *, mode_id: str, gross_credits: float) -> Dict[str, float]:
        listing = self.get_listing(mode_id=mode_id, include_private=True)
        if listing is None:
            raise ValueError("mode_not_found")

        billing_policy = listing.get("billing_policy") if isinstance(listing.get("billing_policy"), dict) else {}
        creator_share_pct = float(billing_policy.get("revenue_share_creator_pct", 0.7))
        creator_share_pct = max(0.0, min(1.0, creator_share_pct))

        gross_credits_value = max(0.0, float(gross_credits))
        creator_share_credits = round(gross_credits_value * creator_share_pct, 6)
        platform_share_credits = round(gross_credits_value - creator_share_credits, 6)

        return {
            "gross_credits": round(gross_credits_value, 6),
            "creator_share_credits": creator_share_credits,
            "platform_share_credits": platform_share_credits,
            "creator_share_pct": round(creator_share_pct, 6),
        }

    def record_usage_event(
        self,
        *,
        mode_id: str,
        consumer_user_id: str,
        event_type: str,
        credits: float = 0.0,
        cost_usd: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_mode_id = str(mode_id or "").strip()
        if not normalized_mode_id:
            raise ValueError("mode_id is required")
        if self.get_listing(mode_id=normalized_mode_id, include_private=True) is None:
            raise ValueError("mode_not_found")

        normalized_consumer = str(consumer_user_id or "").strip()
        if not normalized_consumer:
            raise ValueError("consumer_user_id is required")

        normalized_event_type = str(event_type or "").strip()
        if not normalized_event_type:
            raise ValueError("event_type is required")

        split = self.estimate_revenue_split(mode_id=normalized_mode_id, gross_credits=credits)
        metadata_payload = metadata if isinstance(metadata, dict) else {}
        cost_value = max(0.0, float(cost_usd))

        self._db.execute(
            """
            INSERT INTO marketplace_usage_events(
                mode_id, consumer_user_id, event_type, credits, cost_usd, gross_credits,
                creator_share_credits, platform_share_credits, metadata_json, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                normalized_mode_id,
                normalized_consumer,
                normalized_event_type,
                split["gross_credits"],
                round(cost_value, 6),
                split["gross_credits"],
                split["creator_share_credits"],
                split["platform_share_credits"],
                _to_json(metadata_payload),
            ),
        )

        return {
            "mode_id": normalized_mode_id,
            "consumer_user_id": normalized_consumer,
            "event_type": normalized_event_type,
            "cost_usd": round(cost_value, 6),
            **split,
            "metadata": metadata_payload,
        }

    def export_usage(self, *, mode_id: str, hours: int = 24) -> Dict[str, Any]:
        normalized_mode_id = str(mode_id or "").strip()
        if not normalized_mode_id:
            raise ValueError("mode_id is required")

        lookback_hours = max(1, min(720, int(hours)))
        rows = self._db.fetchall(
            """
            SELECT event_type, credits, cost_usd, gross_credits, creator_share_credits, platform_share_credits, created_at
            FROM marketplace_usage_events
            WHERE mode_id = ? AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC
            """,
            (normalized_mode_id, f"-{lookback_hours} hours"),
        )

        total_credits = 0.0
        total_cost_usd = 0.0
        total_creator_share = 0.0
        total_platform_share = 0.0
        by_event_type: Dict[str, int] = {}

        for row in rows:
            total_credits += float(row["gross_credits"] or 0.0)
            total_cost_usd += float(row["cost_usd"] or 0.0)
            total_creator_share += float(row["creator_share_credits"] or 0.0)
            total_platform_share += float(row["platform_share_credits"] or 0.0)
            event_type = str(row["event_type"] or "unknown")
            by_event_type[event_type] = by_event_type.get(event_type, 0) + 1

        return {
            "mode_id": normalized_mode_id,
            "window_hours": lookback_hours,
            "event_count": len(rows),
            "events_by_type": by_event_type,
            "totals": {
                "gross_credits": round(total_credits, 6),
                "cost_usd": round(total_cost_usd, 6),
                "creator_share_credits": round(total_creator_share, 6),
                "platform_share_credits": round(total_platform_share, 6),
            },
        }

    def _payout_from_row(self, row: Any) -> Dict[str, Any]:
        return {
            "payout_id": str(row["payout_id"]),
            "mode_id": str(row["mode_id"] or ""),
            "owner_tenant_id": str(row["owner_tenant_id"] or ""),
            "currency": str(row["currency"] or "credits"),
            "settlement_window_days": int(row["settlement_window_days"] or 30),
            "window_start": str(row["window_start"] or ""),
            "window_end": str(row["window_end"] or ""),
            "event_count": int(row["event_count"] or 0),
            "gross_credits": round(float(row["gross_credits"] or 0.0), 6),
            "creator_share_credits": round(float(row["creator_share_credits"] or 0.0), 6),
            "platform_share_credits": round(float(row["platform_share_credits"] or 0.0), 6),
            "minimum_payout_credits": round(float(row["minimum_payout_credits"] or 0.0), 6),
            "payout_eligible": bool(int(row["payout_eligible"] or 0)),
            "status": str(row["status"] or "pending"),
            "run_id": str(row["run_id"] or ""),
            "metadata": _parse_json(row["metadata_json"]),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }

    def get_payout(self, *, payout_id: str) -> Optional[Dict[str, Any]]:
        normalized_payout_id = str(payout_id or "").strip()
        if not normalized_payout_id:
            return None
        row = self._db.fetchone(
            """
            SELECT payout_id, mode_id, owner_tenant_id, currency, settlement_window_days, window_start, window_end,
                   event_count, gross_credits, creator_share_credits, platform_share_credits, minimum_payout_credits,
                   payout_eligible, status, run_id, metadata_json, created_at, updated_at
            FROM marketplace_payout_ledger
            WHERE payout_id = ?
            """,
            (normalized_payout_id,),
        )
        return self._payout_from_row(row) if row is not None else None

    def list_payouts(
        self,
        *,
        mode_id: Optional[str] = None,
        owner_tenant_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        normalized_mode_id = str(mode_id or "").strip()
        if normalized_mode_id:
            clauses.append("mode_id = ?")
            params.append(normalized_mode_id)

        normalized_owner = str(owner_tenant_id or "").strip()
        if normalized_owner:
            clauses.append("owner_tenant_id = ?")
            params.append(normalized_owner)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        safe_limit = max(1, min(500, int(limit)))
        rows = self._db.fetchall(
            f"""
            SELECT payout_id, mode_id, owner_tenant_id, currency, settlement_window_days, window_start, window_end,
                   event_count, gross_credits, creator_share_credits, platform_share_credits, minimum_payout_credits,
                   payout_eligible, status, run_id, metadata_json, created_at, updated_at
            FROM marketplace_payout_ledger
            {where_sql}
            ORDER BY created_at DESC
            LIMIT {safe_limit}
            """,
            tuple(params),
        )
        return [self._payout_from_row(row) for row in rows]

    def run_settlement(
        self,
        *,
        run_id: str,
        mode_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            raise ValueError("run_id is required")

        target_modes: List[str] = []
        normalized_mode_id = str(mode_id or "").strip()
        if normalized_mode_id:
            if self.get_listing(mode_id=normalized_mode_id, include_private=True) is None:
                raise ValueError("mode_not_found")
            target_modes = [normalized_mode_id]
        else:
            rows = self._db.fetchall(
                """
                SELECT mode_id
                FROM marketplace_modules
                WHERE status = 'active'
                ORDER BY mode_id ASC
                """
            )
            target_modes = [str(row["mode_id"]) for row in rows]

        created: List[Dict[str, Any]] = []
        skipped_existing = 0
        skipped_below_minimum = 0

        for current_mode in target_modes:
            listing = self.get_listing(mode_id=current_mode, include_private=True)
            if listing is None:
                continue

            billing_policy = listing.get("billing_policy") if isinstance(listing.get("billing_policy"), dict) else {}
            settlement_window_days = int(billing_policy.get("settlement_window_days", 30))
            settlement_window_days = max(1, min(365, settlement_window_days))
            minimum_payout_credits = float(billing_policy.get("minimum_payout_credits", 100.0))
            minimum_payout_credits = max(0.0, minimum_payout_credits)
            currency = str(billing_policy.get("currency") or "credits").strip().lower() or "credits"

            window_start_modifier = f"-{settlement_window_days} days"

            computed_window = self._db.fetchone(
                """
                SELECT
                    datetime(date('now', '+1 day', ?)) AS window_start,
                    datetime(date('now', '+1 day')) AS window_end
                """,
                (window_start_modifier,),
            )
            if computed_window is None:
                continue
            window_start_value = str(computed_window["window_start"] or "")
            window_end_value = str(computed_window["window_end"] or "")
            if not window_start_value or not window_end_value:
                continue

            aggregate = self._db.fetchone(
                """
                SELECT
                    COUNT(*) AS event_count,
                    COALESCE(SUM(gross_credits), 0.0) AS gross_credits,
                    COALESCE(SUM(creator_share_credits), 0.0) AS creator_share_credits,
                    COALESCE(SUM(platform_share_credits), 0.0) AS platform_share_credits,
                    MIN(created_at) AS first_event_at,
                    MAX(created_at) AS last_event_at
                FROM marketplace_usage_events
                WHERE mode_id = ? AND created_at >= ? AND created_at < ?
                """,
                (current_mode, window_start_value, window_end_value),
            )
            event_count = int((aggregate["event_count"] if aggregate else 0) or 0)
            gross_credits = round(float((aggregate["gross_credits"] if aggregate else 0.0) or 0.0), 6)
            creator_share_credits = round(float((aggregate["creator_share_credits"] if aggregate else 0.0) or 0.0), 6)
            platform_share_credits = round(float((aggregate["platform_share_credits"] if aggregate else 0.0) or 0.0), 6)

            existing = self._db.fetchone(
                """
                SELECT payout_id
                FROM marketplace_payout_ledger
                WHERE mode_id = ? AND window_start = ? AND window_end = ?
                """,
                (current_mode, window_start_value, window_end_value),
            )
            if existing is not None:
                skipped_existing += 1
                continue

            payout_eligible = creator_share_credits >= minimum_payout_credits
            if not payout_eligible:
                skipped_below_minimum += 1

            payout_fingerprint = f"{current_mode}|{window_start_value}|{window_end_value}".encode("utf-8")
            payout_id = "payout_" + hashlib.sha256(payout_fingerprint).hexdigest()[:24]
            status = "ready" if payout_eligible else "below_minimum"
            metadata = {
                "first_event_at": str(aggregate["first_event_at"] or ""),
                "last_event_at": str(aggregate["last_event_at"] or ""),
                "source": "marketplace_settlement_v1",
            }

            self._db.execute(
                """
                INSERT INTO marketplace_payout_ledger(
                    payout_id, mode_id, owner_tenant_id, currency, settlement_window_days, window_start, window_end,
                    event_count, gross_credits, creator_share_credits, platform_share_credits, minimum_payout_credits,
                    payout_eligible, status, run_id, metadata_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    payout_id,
                    current_mode,
                    str(listing.get("owner_tenant_id") or ""),
                    currency,
                    settlement_window_days,
                    window_start_value,
                    window_end_value,
                    event_count,
                    gross_credits,
                    creator_share_credits,
                    platform_share_credits,
                    round(minimum_payout_credits, 6),
                    1 if payout_eligible else 0,
                    status,
                    normalized_run_id,
                    _to_json(metadata),
                ),
            )
            stored = self.get_payout(payout_id=payout_id)
            if stored is not None:
                created.append(stored)

        return {
            "run_id": normalized_run_id,
            "mode_filter": normalized_mode_id or None,
            "created_count": len(created),
            "skipped_existing_count": skipped_existing,
            "skipped_below_minimum_count": skipped_below_minimum,
            "created": created,
        }

    def runtime_context(self, *, mode_id: str) -> Optional[Dict[str, Any]]:
        listing = self.get_listing(mode_id=mode_id, include_private=True)
        if listing is None or listing.get("status") != "active":
            return None

        reputation = listing.get("reputation") if isinstance(listing.get("reputation"), dict) else self.get_reputation(mode_id)
        billing_policy = listing.get("billing_policy") if isinstance(listing.get("billing_policy"), dict) else {}
        sandbox_policy = listing.get("sandbox_policy") if isinstance(listing.get("sandbox_policy"), dict) else {}

        return {
            "mode_id": listing["mode_id"],
            "owner_tenant_id": listing["owner_tenant_id"],
            "visibility": listing["visibility"],
            "trust_score": float(reputation.get("trust_score", 0.0)),
            "trust_tier": str(reputation.get("trust_tier", "new")),
            "revenue_share_creator_pct": float(billing_policy.get("revenue_share_creator_pct", 0.7)),
            "monetization_enabled": bool(billing_policy.get("monetization_enabled", True)),
            "allowed_capabilities": _string_list(sandbox_policy.get("allowed_capabilities")),
            "blocked_capabilities": _string_list(sandbox_policy.get("blocked_capabilities")),
        }
