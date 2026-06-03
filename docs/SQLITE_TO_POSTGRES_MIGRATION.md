# SQLite → PostgreSQL Migration – Decision & Path
## Status: **DEFERRED** (Phase 5.4)

_Decision made during Phase 5 architecture refactor. Last updated: 2025._

---

## Decision

SQLite remains the primary data store for the core `seed_server` domain
(users, plans, subscriptions, runs, modules, flows, learning profiles, etc.).

PostgreSQL is already used for the **NeoEats subsystem** (sagas, inventory,
orders, receipts) via `AsyncPGDatabase`.

A full migration is **deferred** because:

1. **Scope** – 691-line schema with 15+ tables, all using SQLite-specific
   syntax (`datetime('now')`, `?` parameter binding, `PRAGMA` directives,
   `ON CONFLICT` with SQLite semantics).
2. **Call sites** – Hundreds of raw SQL queries across ~25 modules use `?`
   placeholders (SQLite) rather than `$1` (asyncpg) or `%s` (psycopg2).
3. **Date functions** – `datetime('now')`, `date('now', '+N days')`,
   `strftime()` appear throughout. Postgres equivalents differ.
4. **Risk** – Rated **Very High** in the roadmap. A botched migration would
   break every API endpoint simultaneously.
5. **Value** – SQLite with WAL mode handles the current request volume
   comfortably. The NeoEats subsystem already proves Postgres works where
   needed.

---

## Recommended Migration Path (when the time comes)

### Phase A: Database Protocol Adapter (1 week)

Create `app/core/interfaces/database.py`:

```python
from typing import Protocol, Any, Optional

class DatabaseProtocol(Protocol):
    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]: ...
    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]: ...
    def transaction(self): ...  # context manager
```

Make `DB` (SQLite) conform. Create `PgDB` wrapper around `AsyncPGDatabase`
that also conforms. All callers import `DatabaseProtocol`.

### Phase B: SQL Abstraction Layer (2 weeks)

Replace raw SQL strings with query builder methods or parameterized templates
that emit the correct dialect:

```python
# Before
db.execute("INSERT INTO users ... VALUES(?, ?)", (id, email))

# After
db.execute(queries.insert_user(id, email))  # returns dialect-aware SQL
```

### Phase C: Table-by-Table Migration (1 table per sprint)

Behind a feature flag, migrate one table at a time:

1. `plans` and `subscriptions` (read-heavy, low risk)
2. `users` (medium risk, needs careful key migration)
3. `runs`, `jobs` (high volume)
4. `modules`, `flows` (complex schemas)
5. `learning_profiles`, `tracks` (data integrity critical)

Each migration:
- Dual-write to both SQLite and Postgres
- Read from Postgres, fallback to SQLite
- Validate data consistency
- Cut over when confident

### Phase D: Remove SQLite (1 week)

Once all tables are on Postgres:
- Remove `DB` class and SQLite schema
- Remove dual-write logic
- Update all configuration

---

## Prerequisites

Before starting:
- [ ] `DatabaseProtocol` interface defined (Phase A)
- [ ] Feature flag for per-table migration toggle
- [ ] Data consistency validation tooling
- [ ] Backup/rollback procedures documented
- [ ] Load testing confirms Postgres handles production query patterns

---

## References

- Roadmap task 5.4: "Consider migrating SQLite to Postgres for all data"
- Risk rating: **Very high** — fundamental migration
- Current SQLite schema: `app/infrastructure/db/sqlite.py` (691 lines, 15+ tables)
- Existing Postgres usage: `app/infrastructure/db/postgres.py` (NeoEats/saga only)
