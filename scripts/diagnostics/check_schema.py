from app.infrastructure.db.sqlite import DB

db = DB(':memory:')
db.init_schema()

tables = db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables with 'unit' or 'node':")
for t in tables:
    if 'unit' in t['name'] or 'node' in t['name']:
        print(f"  ✅ {t['name']}")

