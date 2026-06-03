#!/usr/bin/env python3
"""Check learning profiles."""

from app.infrastructure.db.sqlite import DB
import json

db = DB('./seed.db')

# Get all profiles
rows = db.fetchall('SELECT user_id, version, updated_at FROM learning_profiles ORDER BY updated_at DESC')

print(f"\nПоследние профили в learning_profiles ({len(rows)}):")
print("="*60)

for i, row in enumerate(rows, 1):
    print(f"{i}. {row['user_id'][:35]:35} | v{row['version']} | {row['updated_at']}")

print("="*60)

# Check if any are recent (last hour)
from datetime import datetime, timezone, timedelta
now = datetime.now(timezone.utc)
one_hour_ago = now - timedelta(hours=1)

recent_count = 0
for row in rows:
    updated = datetime.fromisoformat(row['updated_at'].replace('Z', '+00:00'))
    if updated > one_hour_ago:
        recent_count += 1

print(f"\nОбновлений за последний час: {recent_count}")
if recent_count > 0:
    print("✅ Новые профили приходили!")
else:
    print("❌ Новых профилей не было")

