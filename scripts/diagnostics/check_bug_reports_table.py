#!/usr/bin/env python3
"""Check if bug_reports table exists in database."""
from app.infrastructure.db.sqlite import DB

db = DB('/data/db.sqlite')
cursor = db._conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='bug_reports'"
)
result = cursor.fetchone()
print(f"bug_reports table exists: {result is not None}")

if result:
    # Show table schema
    cursor = db._conn.execute("PRAGMA table_info(bug_reports)")
    columns = cursor.fetchall()
    print("\nTable schema:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")

