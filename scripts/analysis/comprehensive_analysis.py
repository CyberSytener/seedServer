"""
Comprehensive analysis of baseline vs optimized prompts
Analyzes all 23 items from each session
"""
import json
from pathlib import Path
from collections import Counter

def analyze_items(items, label):
    """Analyze items and find errors"""
    print(f"\n{'=' * 80}")
    print(f"🔍 ANALYSIS: {label}")
    print('=' * 80)
    
    errors = []
    warnings = []
    task_types = Counter()
    cefr_levels = Counter()
    skills = Counter()
    subskills = Counter()
    topics = Counter()
    difficulties = []
    id_formats = []
    
    for i, item in enumerate(items, 1):
        item_id = item.get("id", "unknown")
        id_formats.append(len(item_id))
        task_type = item.get("taskType", "unknown")
        prompt = item.get("prompt", "")
        tags = item.get("tags", {})
        
        # Stats
        task_types[task_type] += 1
        cefr = tags.get("cefrBand", "unknown")
        cefr_levels[cefr] += 1
        skill = tags.get("skill", "unknown")
        skills[skill] += 1
        subskill = tags.get("subskill", "N/A")
        subskills[subskill] += 1
        topic = tags.get("topic", "N/A")
        topics[topic] += 1
        diff = tags.get("difficulty")
        if diff:
            difficulties.append(diff)
        
        # Validation
        if not prompt or len(prompt) < 5:
            errors.append(f"#{i} [{item_id}]: Empty/short prompt")
        
        if task_type == "mcq":
            choices = item.get("choices", [])
            if len(choices) != 4:
                errors.append(f"#{i} [{item_id}]: MCQ needs 4 choices, has {len(choices)}")
            
            answer = item.get("answer", {})
            accepted = answer.get("accepted", [])
            if not accepted:
                errors.append(f"#{i} [{item_id}]: No accepted answer")
            elif len(accepted) > 0 and accepted[0] not in choices:
                errors.append(f"#{i} [{item_id}]: Answer '{accepted[0]}' not in choices")
            
            distractors = item.get("distractorsReason", [])
            if len(distractors) != 3:
                warnings.append(f"#{i} [{item_id}]: MCQ should have 3 distractor reasons, has {len(distractors)}")
        
        elif task_type == "fill_blank":
            answer = item.get("answer", {})
            if not answer.get("accepted"):
                errors.append(f"#{i} [{item_id}]: No accepted answer")
            if "_" not in prompt and "___" not in prompt:
                warnings.append(f"#{i} [{item_id}]: fill_blank without blank marker")
        
        elif task_type == "translate":
            answer = item.get("answer", {})
            if not answer.get("accepted"):
                errors.append(f"#{i} [{item_id}]: No accepted answer")
        
        elif task_type == "reorder_sentence":
            tokens = item.get("tokens", [])
            answer = item.get("answer", {})
            if not tokens:
                errors.append(f"#{i} [{item_id}]: No tokens array")
            if not answer.get("accepted"):
                errors.append(f"#{i} [{item_id}]: No accepted answer")
        
        elif task_type == "reading_mcq":
            context = item.get("context", {})
            passage = context.get("passage", "")
            if not passage:
                errors.append(f"#{i} [{item_id}]: reading_mcq without passage")
            choices = item.get("choices", [])
            if len(choices) != 4:
                errors.append(f"#{i} [{item_id}]: reading_mcq needs 4 choices")
        
        # Check metadata completeness
        if not cefr or cefr == "unknown":
            warnings.append(f"#{i} [{item_id}]: Missing CEFR")
        if not skill or skill == "unknown":
            warnings.append(f"#{i} [{item_id}]: Missing skill")
        if not subskill or subskill == "N/A":
            warnings.append(f"#{i} [{item_id}]: Missing subskill")
    
    # Statistics
    print(f"\n📊 STATISTICS ({len(items)} items):")
    print(f"   Task types: {dict(task_types)}")
    print(f"   CEFR levels: {dict(cefr_levels)}")
    print(f"   Skills: {dict(skills)}")
    print(f"   Top subskills: {dict(subskills.most_common(5))}")
    print(f"   Top topics: {dict(topics.most_common(5))}")
    
    if difficulties:
        avg_diff = sum(difficulties) / len(difficulties)
        print(f"   Difficulty: min={min(difficulties):.1f}, max={max(difficulties):.1f}, avg={avg_diff:.2f}")
    
    if id_formats:
        avg_id_len = sum(id_formats) / len(id_formats)
        print(f"   ID format: min={min(id_formats)}, max={max(id_formats)}, avg={avg_id_len:.1f} chars")
    
    # Quality metrics
    variety_score = len(task_types) + len(cefr_levels) + len(skills)
    print(f"\n🎯 QUALITY SCORE: {variety_score}/15 (task types + CEFR + skills)")
    
    # Errors
    if errors:
        print(f"\n❌ ERRORS ({len(errors)}):")
        for error in errors[:15]:
            print(f"   {error}")
        if len(errors) > 15:
            print(f"   ... +{len(errors)-15} more")
    else:
        print("\n✅ NO ERRORS!")
    
    # Warnings
    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for warning in warnings[:10]:
            print(f"   {warning}")
        if len(warnings) > 10:
            print(f"   ... +{len(warnings)-10} more")
    
    return {
        "errors": errors,
        "warnings": warnings,
        "task_types": dict(task_types),
        "cefr_levels": dict(cefr_levels),
        "skills": dict(skills),
        "variety_score": variety_score,
        "avg_difficulty": sum(difficulties) / len(difficulties) if difficulties else 0,
        "avg_id_length": sum(id_formats) / len(id_formats) if id_formats else 0
    }

# Load data
baseline_file = Path(__file__).parent / "baseline_items.json"
optimized_file = Path(__file__).parent / "optimized_items.json"

if not baseline_file.exists() or not optimized_file.exists():
    print("❌ Item files not found!")
    exit(1)

baseline_items = json.loads(baseline_file.read_text(encoding='utf-8'))
optimized_items = json.loads(optimized_file.read_text(encoding='utf-8'))

print("=" * 80)
print("🔬 COMPREHENSIVE DIAGNOSTIC QUALITY ANALYSIS")
print("=" * 80)
print(f"\nBaseline items: {len(baseline_items)}")
print(f"Optimized items: {len(optimized_items)}")

# Analyze
baseline_analysis = analyze_items(baseline_items, "BASELINE")
optimized_analysis = analyze_items(optimized_items, "OPTIMIZED")

# Comparison
print("\n\n" + "=" * 80)
print("📊 COMPARISON SUMMARY")
print("=" * 80)

print(f"\n🔍 ERROR COUNT:")
print(f"   Baseline:  {len(baseline_analysis['errors'])}")
print(f"   Optimized: {len(optimized_analysis['errors'])}")
if len(optimized_analysis['errors']) < len(baseline_analysis['errors']):
    print(f"   ✅ Optimized has {len(baseline_analysis['errors']) - len(optimized_analysis['errors'])} fewer errors!")
elif len(optimized_analysis['errors']) > len(baseline_analysis['errors']):
    print(f"   ⚠️  Optimized has {len(optimized_analysis['errors']) - len(baseline_analysis['errors'])} MORE errors!")
else:
    print(f"   ➡️  Same error count")

print(f"\n⚠️  WARNING COUNT:")
print(f"   Baseline:  {len(baseline_analysis['warnings'])}")
print(f"   Optimized: {len(optimized_analysis['warnings'])}")

print(f"\n🎯 VARIETY:")
print(f"   Baseline:  {baseline_analysis['variety_score']}/15")
print(f"   Optimized: {optimized_analysis['variety_score']}/15")

print(f"\n📏 DIFFICULTY:")
print(f"   Baseline:  {baseline_analysis['avg_difficulty']:.2f}")
print(f"   Optimized: {optimized_analysis['avg_difficulty']:.2f}")

print(f"\n🆔 ID FORMAT:")
print(f"   Baseline:  {baseline_analysis['avg_id_length']:.1f} chars")
print(f"   Optimized: {optimized_analysis['avg_id_length']:.1f} chars")

# Recommendations
print("\n\n" + "=" * 80)
print("💡 RECOMMENDATIONS FOR PROMPT IMPROVEMENT")
print("=" * 80)

all_errors = set([e.split(']:')[1].strip() for e in baseline_analysis['errors'] + optimized_analysis['errors'] if ']:' in e])
all_warnings = set([w.split(']:')[1].strip() for w in baseline_analysis['warnings'] + optimized_analysis['warnings'] if ']:' in w])

if all_errors:
    print("\n🔴 CRITICAL ISSUES TO FIX:")
    for i, error_type in enumerate(sorted(all_errors)[:5], 1):
        print(f"   {i}. {error_type}")

if all_warnings:
    print("\n🟡 WARNINGS TO ADDRESS:")
    for i, warning_type in enumerate(sorted(all_warnings)[:5], 1):
        print(f"   {i}. {warning_type}")

print("\n" + "=" * 80)
print("✅ Analysis complete!")
print("=" * 80)
