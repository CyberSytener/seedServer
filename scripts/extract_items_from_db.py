"""
Extract and analyze ALL items from recent diagnostic sessions
"""
import json
import sqlite3
from pathlib import Path
from collections import Counter

db_path = Path(__file__).parent / "seed.db"

if not db_path.exists():
    print(f"❌ Database not found: {db_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

# Get 2 most recent sessions
cursor = conn.execute("""
    SELECT id, user_id, native_lang, target_lang, status, created_at
    FROM diagnostic_sessions
    ORDER BY created_at DESC
    LIMIT 2
""")

sessions = cursor.fetchall()

if len(sessions) < 2:
    print(f"❌ Need at least 2 sessions, found {len(sessions)}")
    exit(1)

print("=" * 80)
print("📦 EXTRACTING ITEMS FROM DATABASE")
print("=" * 80)

for i, session in enumerate(sessions, 1):
    session_id = session['id']
    print(f"\n{'🔵' if i == 1 else '🟢'} Session {i}: {session_id}")
    print(f"   User: {session['user_id']}")
    print(f"   Languages: {session['native_lang']} → {session['target_lang']}")
    print(f"   Created: {session['created_at']}")
    
    # Get items
    cursor = conn.execute("""
        SELECT item_id, item_json, order_index
        FROM diagnostic_session_items
        WHERE session_id = ?
        ORDER BY order_index
    """, (session_id,))
    
    items_raw = cursor.fetchall()
    items = []
    
    for item_row in items_raw:
        item_json = json.loads(item_row['item_json'])
        items.append(item_json)
    
    print(f"   Items: {len(items)}")
    
    # Save to file
    filename = f"{'baseline' if i == 1 else 'test'}_items_from_db.json"
    output_file = Path(__file__).parent / filename
    output_file.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    print(f"   💾 Saved to: {filename}")
    
    # Analyze quality
    print(f"\n   🔍 QUALITY ANALYSIS:")
    
    errors = []
    warnings = []
    task_types = Counter()
    cefr_levels = Counter()
    skills = Counter()
    
    for j, item in enumerate(items, 1):
        item_id = item.get("id", "unknown")
        task_type = item.get("taskType", "unknown")
        prompt = item.get("prompt", "")
        tags = item.get("tags", {})
        
        task_types[task_type] += 1
        cefr = tags.get("cefrBand", "unknown")
        cefr_levels[cefr] += 1
        skill = tags.get("skill", "unknown")
        skills[skill] += 1
        
        # Validate
        if not prompt or len(prompt) < 5:
            errors.append(f"Item {j} ({item_id}): Empty/short prompt")
        
        if task_type == "mcq":
            choices = item.get("choices", [])
            if len(choices) != 4:
                errors.append(f"Item {j} ({item_id}): MCQ needs 4 choices, has {len(choices)}")
            
            answer = item.get("answer", {})
            accepted = answer.get("accepted", [])
            if not accepted:
                errors.append(f"Item {j} ({item_id}): No accepted answer")
            elif accepted[0] not in choices:
                errors.append(f"Item {j} ({item_id}): Answer not in choices")
        
        elif task_type == "fill_blank":
            answer = item.get("answer", {})
            if not answer.get("accepted"):
                errors.append(f"Item {j} ({item_id}): No accepted answer")
            if "_" not in prompt and "___" not in prompt:
                warnings.append(f"Item {j} ({item_id}): fill_blank without blank marker")
        
        elif task_type == "translate":
            answer = item.get("answer", {})
            if not answer.get("accepted"):
                errors.append(f"Item {j} ({item_id}): No accepted answer")
        
        elif task_type == "reorder_sentence":
            tokens = item.get("tokens", [])
            answer = item.get("answer", {})
            if not tokens:
                errors.append(f"Item {j} ({item_id}): No tokens")
            if not answer.get("accepted"):
                errors.append(f"Item {j} ({item_id}): No accepted answer")
        
        elif task_type == "reading_mcq":
            context = item.get("context", {})
            passage = context.get("passage", "")
            if not passage:
                errors.append(f"Item {j} ({item_id}): reading_mcq without passage")
            choices = item.get("choices", [])
            if len(choices) != 4:
                errors.append(f"Item {j} ({item_id}): reading_mcq needs 4 choices")
    
    # Print stats
    print(f"      Task types: {dict(task_types)}")
    print(f"      CEFR: {dict(cefr_levels)}")
    print(f"      Skills: {dict(skills)}")
    
    if errors:
        print(f"\n      ❌ ERRORS ({len(errors)}):")
        for error in errors[:10]:
            print(f"         - {error}")
        if len(errors) > 10:
            print(f"         ... +{len(errors)-10} more")
    else:
        print(f"\n      ✅ No errors!")
    
    if warnings:
        print(f"\n      ⚠️  WARNINGS ({len(warnings)}):")
        for warning in warnings[:5]:
            print(f"         - {warning}")

conn.close()

print("\n" + "=" * 80)
print("✅ Extraction complete!")
print("=" * 80)
print("\nFiles created:")
print("  - baseline_items_from_db.json")
print("  - test_items_from_db.json")
