"""
Comprehensive diagnostic quality analysis
Collects ALL items from both baseline and test sessions
"""
import json
import requests
import time
import subprocess
from pathlib import Path
from collections import Counter

# Config
base_url = "http://localhost:8000"
env_file = Path(__file__).parent / ".env"

# Load keys
api_key = None
admin_key = None
if env_file.exists():
    for line in env_file.read_text().split('\n'):
        if line.startswith('SEED_ADMIN_API_KEY='):
            api_key = line.split('=', 1)[1].strip()
        elif line.startswith('SEED_ADMIN_KEY='):
            admin_key = line.split('=', 1)[1].strip()

if not api_key or not admin_key:
    print("❌ No keys found")
    exit(1)

headers = {
    "Authorization": f"Bearer {api_key}",
    "X-Admin-Key": admin_key
}

def toggle_test_mode(enable: bool):
    """Toggle test mode and restart API"""
    env_text = env_file.read_text()
    lines = []
    found = False
    
    for line in env_text.split('\n'):
        if line.startswith('SEED_PROMPT_TEST_MODE='):
            lines.append(f"SEED_PROMPT_TEST_MODE={'true' if enable else 'false'}")
            found = True
        else:
            lines.append(line)
    
    if not found:
        lines.append(f"SEED_PROMPT_TEST_MODE={'true' if enable else 'false'}")
    
    env_file.write_text('\n'.join(lines))
    
    print(f"  {'Enabling' if enable else 'Disabling'} test mode...")
    subprocess.run(["docker-compose", "restart", "api"], capture_output=True)
    time.sleep(3)
    
    for _ in range(10):
        try:
            resp = requests.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                return
        except:
            pass
        time.sleep(1)

def collect_all_items(user_key, test_name):
    """Collect ALL items from diagnostic session"""
    user_headers = {"Authorization": f"Bearer {user_key}"}
    
    print(f"\n{'=' * 80}")
    print(f"📦 COLLECTING: {test_name}")
    print('=' * 80)
    
    start_time = time.time()
    
    session_resp = requests.post(
        f"{base_url}/v1/learning/diagnostic/start",
        headers=user_headers,
        json={
            "nativeLanguage": "English",
            "targetLanguage": "Spanish",
            "startLevelGuess": "A2"
        }
    )
    
    if session_resp.status_code != 200:
        print(f"❌ Failed: {session_resp.json()}")
        return None
    
    session_data = session_resp.json()
    session_id = session_data["sessionId"]
    total_items = session_data.get("totalItems", 0)
    
    items = []
    first_item = session_data.get("nextItem")
    if first_item:
        items.append(first_item)
    
    # Collect remaining items
    print(f"Collecting {total_items} items...", end="", flush=True)
    while len(items) < total_items:
        next_resp = requests.post(
            f"{base_url}/v1/learning/diagnostic/next",
            headers=user_headers,
            json={"sessionId": session_id, "requestCount": 1}
        )
        if next_resp.status_code == 200:
            next_data = next_resp.json()
            next_item = next_data.get("nextItem")
            if next_item:
                items.append(next_item)
                print(".", end="", flush=True)
            else:
                break
        else:
            break
    
    elapsed = time.time() - start_time
    print(f"\n✅ Collected {len(items)} items in {elapsed:.2f}s")
    
    return {
        "session_id": session_id,
        "time": elapsed,
        "items": items
    }

def analyze_quality(items, label):
    """Analyze item quality and find errors"""
    print(f"\n{'=' * 80}")
    print(f"🔍 QUALITY ANALYSIS: {label}")
    print('=' * 80)
    
    errors = []
    warnings = []
    
    task_types = Counter()
    cefr_levels = Counter()
    skills = Counter()
    difficulties = []
    
    for i, item in enumerate(items, 1):
        item_id = item.get("itemId", "unknown")
        task_type = item.get("taskType", "unknown")
        prompt = item.get("prompt", "")
        metadata = item.get("metadata", {})
        content = item.get("content", {})
        
        # Collect stats
        task_types[task_type] += 1
        cefr = metadata.get("cefrBand", "unknown")
        cefr_levels[cefr] += 1
        skill = metadata.get("skill", "unknown")
        skills[skill] += 1
        difficulty = metadata.get("difficulty")
        if difficulty:
            difficulties.append(difficulty)
        
        # Validate item
        if not prompt or len(prompt) < 5:
            errors.append(f"Item {i} ({item_id}): Empty or too short prompt")
        
        if task_type == "mcq":
            choices = content.get("choices", [])
            if len(choices) != 4:
                errors.append(f"Item {i} ({item_id}): MCQ should have 4 choices, has {len(choices)}")
            
            answer = content.get("answer", {})
            accepted = answer.get("accepted", [])
            if not accepted:
                errors.append(f"Item {i} ({item_id}): No accepted answer")
            elif accepted[0] not in choices:
                errors.append(f"Item {i} ({item_id}): Answer '{accepted[0]}' not in choices")
        
        elif task_type == "fill_blank":
            answer = content.get("answer", {})
            accepted = answer.get("accepted", [])
            if not accepted:
                errors.append(f"Item {i} ({item_id}): No accepted answer")
            if "_" not in prompt:
                warnings.append(f"Item {i} ({item_id}): fill_blank without underscore")
        
        elif task_type == "translate":
            answer = content.get("answer", {})
            accepted = answer.get("accepted", [])
            if not accepted:
                errors.append(f"Item {i} ({item_id}): No accepted answer")
        
        elif task_type == "reorder_sentence":
            tokens = content.get("tokens", [])
            answer = content.get("answer", {})
            accepted = answer.get("accepted", [])
            if not tokens:
                errors.append(f"Item {i} ({item_id}): No tokens provided")
            if not accepted:
                errors.append(f"Item {i} ({item_id}): No accepted answer")
        
        elif task_type == "reading_mcq":
            context_obj = content.get("context", {})
            passage = context_obj.get("passage", "")
            if not passage:
                errors.append(f"Item {i} ({item_id}): reading_mcq without passage")
            choices = content.get("choices", [])
            if len(choices) != 4:
                errors.append(f"Item {i} ({item_id}): reading_mcq should have 4 choices")
        
        # Check metadata
        if not cefr or cefr == "unknown":
            warnings.append(f"Item {i} ({item_id}): Missing CEFR level")
        
        if not skill or skill == "unknown":
            warnings.append(f"Item {i} ({item_id}): Missing skill")
    
    # Print statistics
    print(f"\n📊 STATISTICS ({len(items)} items):")
    print(f"  Task Types: {dict(task_types)}")
    print(f"  CEFR Distribution: {dict(cefr_levels)}")
    print(f"  Skills: {dict(skills)}")
    if difficulties:
        avg_diff = sum(difficulties) / len(difficulties)
        print(f"  Difficulty: min={min(difficulties)}, max={max(difficulties)}, avg={avg_diff:.2f}")
    
    # Print errors
    if errors:
        print(f"\n❌ ERRORS ({len(errors)}):")
        for error in errors[:10]:
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors)-10} more")
    else:
        print("\n✅ No errors found")
    
    # Print warnings
    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for warning in warnings[:5]:
            print(f"  - {warning}")
        if len(warnings) > 5:
            print(f"  ... and {len(warnings)-5} more")
    
    return {
        "errors": errors,
        "warnings": warnings,
        "task_types": dict(task_types),
        "cefr_levels": dict(cefr_levels),
        "skills": dict(skills),
        "difficulties": difficulties
    }

# Main
print("=" * 80)
print("🔬 COMPREHENSIVE DIAGNOSTIC QUALITY ANALYSIS")
print("=" * 80)

# Test 1: Baseline
print("\n🔵 TEST 1: BASELINE")
toggle_test_mode(False)
user1_resp = requests.post(f"{base_url}/v1/users", headers=headers, json={"id": f"qa_base_{int(time.time())}"})
user1_id, user1_key = user1_resp.json()["user_id"], user1_resp.json()["api_key"]
baseline_data = collect_all_items(user1_key, "BASELINE")

if baseline_data:
    baseline_analysis = analyze_quality(baseline_data["items"], "BASELINE")
    
    # Save to file
    output_file = Path(__file__).parent / "baseline_items.json"
    output_file.write_text(json.dumps(baseline_data["items"], indent=2, ensure_ascii=False))
    print(f"\n💾 Saved to: {output_file.name}")

# Test 2: Test
print("\n\n🟢 TEST 2: OPTIMIZED")
toggle_test_mode(True)
user2_resp = requests.post(f"{base_url}/v1/users", headers=headers, json={"id": f"qa_test_{int(time.time())}"})
user2_id, user2_key = user2_resp.json()["user_id"], user2_resp.json()["api_key"]
test_data = collect_all_items(user2_key, "OPTIMIZED")

if test_data:
    test_analysis = analyze_quality(test_data["items"], "OPTIMIZED")
    
    # Save to file
    output_file = Path(__file__).parent / "test_items.json"
    output_file.write_text(json.dumps(test_data["items"], indent=2, ensure_ascii=False))
    print(f"\n💾 Saved to: {output_file.name}")

# Comparison
if baseline_data and test_data:
    print("\n\n" + "=" * 80)
    print("📊 COMPARISON SUMMARY")
    print("=" * 80)
    
    print(f"\n⏱️  TIME:")
    print(f"  Baseline: {baseline_data['time']:.2f}s")
    print(f"  Test:     {test_data['time']:.2f}s")
    time_diff = test_data['time'] - baseline_data['time']
    time_pct = (time_diff / baseline_data['time']) * 100
    print(f"  Difference: {time_diff:+.2f}s ({time_pct:+.1f}%)")
    
    print(f"\n🔍 QUALITY:")
    print(f"  Baseline errors: {len(baseline_analysis['errors'])}")
    print(f"  Test errors:     {len(test_analysis['errors'])}")
    print(f"  Baseline warnings: {len(baseline_analysis['warnings'])}")
    print(f"  Test warnings:     {len(test_analysis['warnings'])}")
    
    print(f"\n📦 VARIETY:")
    print(f"  Baseline task types: {len(baseline_analysis['task_types'])}")
    print(f"  Test task types:     {len(test_analysis['task_types'])}")
    print(f"  Baseline CEFR levels: {len(baseline_analysis['cefr_levels'])}")
    print(f"  Test CEFR levels:     {len(test_analysis['cefr_levels'])}")
    
    print("\n" + "=" * 80)
    print("✅ Analysis complete!")
    print("=" * 80)
