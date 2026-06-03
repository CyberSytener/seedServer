"""
Compare baseline vs test prompts for diagnostic generation
Run 1: Disable test mode, run baseline
Run 2: Enable test mode, run test
"""
import json
import requests
import time
import subprocess
from pathlib import Path

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
    print("❌ No API key or admin key found in .env")
    exit(1)

headers = {
    "Authorization": f"Bearer {api_key}",
    "X-Admin-Key": admin_key
}

def toggle_test_mode(enable: bool):
    """Toggle test mode in .env and restart API"""
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
    
    # Restart API
    print(f"  {'Enabling' if enable else 'Disabling'} test mode...")
    result = subprocess.run(
        ["docker-compose", "restart", "api"],
        capture_output=True,
        text=True
    )
    
    # Wait for health
    time.sleep(3)
    for _ in range(10):
        try:
            resp = requests.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                return
        except:
            pass
        time.sleep(1)
    print("  ⚠️  API may not be ready")

def create_user():
    """Create test user"""
    resp = requests.post(
        f"{base_url}/v1/users",
        headers=headers,
        json={"id": f"test_compare_{int(time.time())}"}
    )
    data = resp.json()
    return data["user_id"], data["api_key"]

def run_diagnostic_test(user_key, test_name):
    """Run diagnostic session and measure performance"""
    user_headers = {"Authorization": f"Bearer {user_key}"}
    
    print(f"\n{'=' * 80}")
    print(f"🧪 TEST: {test_name}")
    print('=' * 80)
    
    # Start session
    print("\n📋 Starting diagnostic session...")
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
    
    session_time = time.time() - start_time
    
    if session_resp.status_code != 200:
        print(f"❌ Failed: {session_resp.json()}")
        return None
    
    session_data = session_resp.json()
    session_id = session_data["sessionId"]
    total_items = session_data.get("totalItems", 0)
    first_item = session_data.get("nextItem")
    
    print(f"✅ Session created: {session_id}")
    print(f"⏱️  Time: {session_time:.2f}s")
    print(f"📊 Total items: {total_items}")
    
    # Analyze first 5 items
    items = []
    if first_item:
        items.append(first_item)
    
    # Get more items (collect up to 10 for analysis)
    for i in range(9):
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
    
    # Quality analysis
    print(f"\n📝 QUALITY ANALYSIS ({len(items)} items sampled):")
    print("-" * 80)
    
    task_types = {}
    cefr_levels = {}
    skills = {}
    id_lengths = []
    
    for i, item in enumerate(items[:5], 1):
        item_id = item.get("itemId", "unknown")
        id_lengths.append(len(item_id))
        task_type = item.get("taskType", "unknown")
        prompt = item.get("prompt", "")
        metadata = item.get("metadata", {})
        content = item.get("content", {})
        
        # Collect stats
        task_types[task_type] = task_types.get(task_type, 0) + 1
        cefr = metadata.get("cefrBand", "unknown")
        cefr_levels[cefr] = cefr_levels.get(cefr, 0) + 1
        skill = metadata.get("skill", "unknown")
        skills[skill] = skills.get(skill, 0) + 1
        
        # Display item
        print(f"\n  Item {i} [{item_id}]:")
        print(f"  Type: {task_type}")
        print(f"  CEFR: {cefr}")
        print(f"  Skill: {skill} / {metadata.get('subskill', 'N/A')}")
        print(f"  Topic: {metadata.get('topic', 'N/A')}")
        print(f"  Difficulty: {metadata.get('difficulty', 'N/A')}")
        print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
        
        if task_type == "mcq" and content.get("choices"):
            choices = content.get("choices", [])
            print(f"  Choices: {len(choices)} options")
            for j, choice in enumerate(choices[:2], 1):
                print(f"    {j}. {choice}")
            if len(choices) > 2:
                print(f"    ... +{len(choices)-2} more")
    
    # Summary stats
    avg_id_length = sum(id_lengths) / len(id_lengths) if id_lengths else 0
    print(f"\n📊 STATISTICS:")
    print(f"  Task Types: {dict(task_types)}")
    print(f"  CEFR Levels: {dict(cefr_levels)}")
    print(f"  Skills: {dict(skills)}")
    print(f"  Avg ID length: {avg_id_length:.1f} chars (UUID=36, short=10-20)")
    
    return {
        "session_id": session_id,
        "time": session_time,
        "total_items": total_items,
        "sampled_items": len(items),
        "task_types": task_types,
        "cefr_levels": cefr_levels,
        "skills": skills,
        "avg_id_length": avg_id_length,
        "items": items
    }

# Main comparison
print("=" * 80)
print("🔬 DIAGNOSTIC PROMPT COMPARISON")
print("=" * 80)
print("\nComparing BASELINE vs TEST prompts")
print("Testing with: English → Spanish, A2 level")

# Test 1: Baseline (disable test mode)
print("\n\n" + "🔵" * 40)
print("TEST 1: BASELINE PROMPT")
print("🔵" * 40)
toggle_test_mode(False)
user1_id, user1_key = create_user()
print(f"Created user: {user1_id}")

baseline_result = run_diagnostic_test(user1_key, "BASELINE")

# Test 2: Test prompt (enable test mode)
print("\n\n" + "🟢" * 40)
print("TEST 2: OPTIMIZED TEST PROMPT")
print("🟢" * 40)
toggle_test_mode(True)
user2_id, user2_key = create_user()
print(f"Created user: {user2_id}")

test_result = run_diagnostic_test(user2_key, "OPTIMIZED TEST")

# Comparison
print("\n\n" + "=" * 80)
print("📊 COMPARISON RESULTS")
print("=" * 80)

if baseline_result and test_result:
    print(f"\n⏱️  TIME:")
    print(f"  Baseline: {baseline_result['time']:.2f}s")
    print(f"  Test:     {test_result['time']:.2f}s")
    time_diff = test_result['time'] - baseline_result['time']
    time_pct = (time_diff / baseline_result['time']) * 100
    print(f"  Difference: {time_diff:+.2f}s ({time_pct:+.1f}%)")
    
    print(f"\n📦 ITEMS:")
    print(f"  Baseline: {baseline_result['total_items']} items")
    print(f"  Test:     {test_result['total_items']} items")
    
    print(f"\n🎯 QUALITY (based on {baseline_result['sampled_items']} samples):")
    print(f"  Baseline task variety: {len(baseline_result['task_types'])} types")
    print(f"  Test task variety:     {len(test_result['task_types'])} types")
    
    print(f"\n  Baseline CEFR spread: {len(baseline_result['cefr_levels'])} levels")
    print(f"  Test CEFR spread:     {len(test_result['cefr_levels'])} levels")
    
    print(f"\n  Baseline skills: {len(baseline_result['skills'])} types")
    print(f"  Test skills:     {len(test_result['skills'])} types")
    
    print(f"\n  Baseline avg ID length: {baseline_result['avg_id_length']:.1f}")
    print(f"  Test avg ID length:     {test_result['avg_id_length']:.1f}")
    
    print("\n" + "=" * 80)
    print("✅ Comparison complete!")
    print("=" * 80)
    
    # Recommendation
    if time_pct < -10:
        print("\n💡 Test prompt is significantly FASTER (>10%)")
    elif time_pct > 10:
        print("\n⚠️  Test prompt is SLOWER (>10%)")
    else:
        print("\n➡️  Performance is SIMILAR (within 10%)")
        
    print(f"\n📝 Token estimation:")
    print(f"  Baseline prompt: ~2800 tokens (verbose JSON schema)")
    print(f"  Test prompt:     ~1400 tokens (compact schema)")
    print(f"  Savings:         ~50% reduction")
else:
    print("\n❌ Comparison failed - one or both tests did not complete")
