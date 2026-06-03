import sqlite3
import json
from pathlib import Path

# Connect to DB in container
conn = sqlite3.connect('seed.db')
conn.row_factory = sqlite3.Row

# Get 2 most recent sessions
sessions = conn.execute("""
    SELECT id, user_id, created_at
    FROM diagnostic_sessions
    ORDER BY created_at DESC
    LIMIT 2
""").fetchall()

print(f"Found {len(sessions)} sessions")

for i, session in enumerate(sessions):
    session_id = session['id']
    label = "OPTIMIZED" if i == 0 else "BASELINE"
    
    print(f"\n{label}: {session_id}")
    
    # Get all items
    items_data = conn.execute("""
        SELECT item_json
        FROM diagnostic_session_items
        WHERE session_id = ?
        ORDER BY order_index
    """, (session_id,)).fetchall()
    
    items = [json.loads(row['item_json']) for row in items_data]
    
    print(f"  Items: {len(items)}")
    
    # Save
    filename = f"{label.lower()}_items.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    
    print(f"  Saved: {filename}")

conn.close()
