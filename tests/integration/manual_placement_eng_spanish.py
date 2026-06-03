"""
Test placement test: English to Spanish
Measures tokens and time
"""
import json
import requests
import time
from pathlib import Path

# Load API key and admin key
env_file = Path(__file__).parent / ".env"
api_key = None
admin_key = None
base_url = "http://localhost:8000"

if env_file.exists():
    for line in env_file.read_text().split('\n'):
        if line.startswith('SEED_ADMIN_API_KEY='):
            api_key = line.split('=', 1)[1].strip()
        elif line.startswith('SEED_ADMIN_KEY='):
            admin_key = line.split('=', 1)[1].strip()

if not api_key:
    print("❌ No API key found in .env")
    exit(1)
    
if not admin_key:
    print("❌ No admin key found in .env")
    exit(1)

headers = {
    "Authorization": f"Bearer {api_key}",
    "X-Admin-Key": admin_key,
    "Content-Type": "application/json"
}

print("=" * 80)
print("🧪 PLACEMENT TEST: English → Spanish")
print("=" * 80)

# Step 1: Create user
print("\n1️⃣ Creating test user...")
start = time.time()
user_resp = requests.post(
    f"{base_url}/v1/users",
    headers=headers,
    json={"id": f"test_placement_{int(time.time())}"}
)
user_data = user_resp.json()
user_id = user_data["user_id"]
user_key = user_data["api_key"]
user_headers = {"Authorization": f"Bearer {user_key}"}
print(f"✅ User created: {user_id}")
print(f"   Time: {time.time() - start:.2f}s")

# Step 2: Start diagnostic session
print("\n2️⃣ Starting diagnostic session...")
start = time.time()
session_resp = requests.post(
    f"{base_url}/v1/learning/diagnostic/start",
    headers=user_headers,
    json={
        "nativeLanguage": "English",
        "targetLanguage": "Spanish",
        "startLevelGuess": "A2"
    }
)
session_time = time.time() - start
session_data = session_resp.json()
print(f"   Response summary:")
print(f"   - SessionID: {session_data.get('sessionId', 'N/A')}")
print(f"   - Total items: {session_data.get('totalItems', 0)}")
print(f"   - Has first item: {'nextItem' in session_data}")
print(f"   - All keys: {list(session_data.keys())}")

if session_resp.status_code != 200:
    print(f"❌ Session start failed: {session_data}")
    exit(1)

session_id = session_data["sessionId"]
total_items = session_data.get("totalItems", 0)
first_item = session_data.get("nextItem")
print(f"✅ Session started: {session_id}")
print(f"   Time: {session_time:.2f}s")
print(f"   Total items in session: {total_items}")

# Collect all items (starting with the first one)
items = []
tokens_in_total = 0
tokens_out_total = 0
gen_time_total = time.time() - start

if first_item:
    items.append(first_item)
    print(f"   ✅ First item included")

# Step 3: Get more items if needed
print("\n3️⃣ Collecting all diagnostic items...")
while len(items) < 5 and len(items) < total_items:
    start_next = time.time()
    next_resp = requests.post(
        f"{base_url}/v1/learning/diagnostic/next",
        headers=user_headers,
        json={
            "sessionId": session_id,
            "requestCount": 5 - len(items)
        }
    )
    next_time = time.time() - start_next
    next_data = next_resp.json()
    
    if next_resp.status_code != 200:
        print(f"   ⚠️ No more items available")
        break
    
    next_item = next_data.get("nextItem")
    if next_item:
        items.append(next_item)
        print(f"   ✅ Got item {len(items)}")
        
        # Track tokens if available
        tokens_in_total += next_data.get("tokensIn", 0)
        tokens_out_total += next_data.get("tokensOut", 0)
        gen_time_total += next_time
    else:
        break

print(f"✅ Collected {len(items)} items total")
print(f"   Total time: {gen_time_total:.2f}s")
if tokens_in_total + tokens_out_total > 0:
    print(f"   Tokens IN: {tokens_in_total:,}")
    print(f"   Tokens OUT: {tokens_out_total:,}")
    print(f"   Total tokens: {tokens_in_total + tokens_out_total:,}")
    print(f"   Tokens/sec: {(tokens_in_total + tokens_out_total) / gen_time_total:.0f}")

# Step 4: Show sample items
print("\n4️⃣ Sample items:")
for i, item in enumerate(items[:3], 1):
    print(f"\n   Item {i} [{item.get('itemId', 'unknown')}]:")
    print(f"   Type: {item.get('taskType', 'unknown')}")
    print(f"   CEFR: {item.get('cefrBand', 'unknown')}")
    print(f"   Prompt: {item.get('prompt', '')[:100]}...")
    
# Step 5: Submit some answers
print("\n5️⃣ Submitting sample answers...")
correct_count = 0
for i, item in enumerate(items[:3], 1):
    item_id = item.get("itemId")
    correct_answer = item.get("correctAnswer", "")
    
    # Submit correct answer
    start = time.time()
    attempt_resp = requests.post(
        f"{base_url}/v1/learning/diagnostic/attempt",
        headers=user_headers,
        json={
            "sessionId": session_id,
            "itemId": item_id,
            "answer": correct_answer
        }
    )
    attempt_data = attempt_resp.json()
    
    if attempt_data.get("isCorrect"):
        correct_count += 1
        print(f"   ✅ Item {i}: Correct ({time.time() - start:.2f}s)")
    else:
        print(f"   ❌ Item {i}: Incorrect ({time.time() - start:.2f}s)")

# Summary
print("\n" + "=" * 80)
print("📊 SUMMARY")
print("=" * 80)
print(f"Session ID: {session_id}")
print(f"Total items in session: {total_items}")
print(f"Items collected: {len(items)}")
print(f"Generation time: {gen_time_total:.2f}s")
if tokens_in_total + tokens_out_total > 0:
    print(f"Total tokens: {tokens_in_total + tokens_out_total:,}")
    print(f"Tokens IN: {tokens_in_total:,}")
    print(f"Tokens OUT: {tokens_out_total:,}")
    print(f"Throughput: {(tokens_in_total + tokens_out_total) / gen_time_total:.0f} tokens/sec")
print(f"Answers submitted: {min(3, len(items))}")
print(f"Correct answers: {correct_count}")
print("=" * 80)
