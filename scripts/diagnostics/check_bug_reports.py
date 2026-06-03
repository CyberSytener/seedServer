#!/usr/bin/env python3
"""Check bug reports in database."""

from app.infrastructure.db.sqlite import DB
import json

db = DB('./seed.db')

# Get all bug reports
rows = db.fetchall('SELECT id, user_id, kind, severity, payload_json, created_at FROM bug_reports ORDER BY created_at DESC')

print("\n" + "="*80)
print(f"BUG REPORTS IN DATABASE: {len(rows)} total")
print("="*80 + "\n")

if len(rows) == 0:
    print("No bug reports found.")
else:
    for i, row in enumerate(rows, 1):
        payload = json.loads(row['payload_json'])
        
        print(f"Report #{i}")
        print(f"  ID: {row['id']}")
        print(f"  User: {row['user_id']}")
        print(f"  Kind: {row['kind']}")
        print(f"  Severity: {row['severity']}")
        print(f"  Created: {row['created_at']}")
        
        # Show user message if available
        if payload.get('userMessage'):
            print(f"  Message: {payload['userMessage'][:100]}")
        
        # Show context
        context = payload.get('context', {})
        if context:
            print(f"  Context:")
            for key, val in list(context.items())[:5]:
                print(f"    {key}: {val}")
        
        # Show client info
        client = payload.get('client', {})
        if client:
            print(f"  Client:")
            if 'app' in client:
                print(f"    app: {client['app']}")
            if 'appVersion' in client:
                print(f"    version: {client['appVersion']}")
            if 'platform' in client:
                print(f"    platform: {client['platform']}")
        
        print()

print("="*80 + "\n")

