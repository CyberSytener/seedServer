#!/usr/bin/env python3
"""Check desktop user profile."""

from app.infrastructure.db.sqlite import DB
import json

db = DB('./seed.db')

# Get desktop user profile
row = db.fetchone(
    "SELECT user_id, profile_json, updated_at FROM learning_profiles WHERE user_id LIKE 'desktop_%' ORDER BY updated_at DESC LIMIT 1"
)

if not row:
    print("No desktop user profile found")
else:
    profile = json.loads(row['profile_json'])
    hist = profile.get('history')
    
    print("\n" + "="*80)
    print("DESKTOP USER PROFILE")
    print("="*80)
    print(f"User ID: {row['user_id']}")
    print(f"Updated: {row['updated_at']}")
    print(f"Target Language: {profile['targetLanguage']}")
    print(f"Native Language: {profile['nativeLanguage']}")
    print(f"Estimated CEFR: {profile['estimatedCefr']}")
    print(f"Topic: {profile['preferences'].get('topic', 'None')}")
    print(f"\nSkill Scores:")
    for skill in profile['skillScores']:
        print(f"  {skill['skill']:15} {skill['score']:3}/100")
    
    print(f"\nWeak Subskills ({len(profile['weakSubskills'])}):")
    for weak in profile['weakSubskills']:
        print(f"  {weak['skill']:15} / {weak['subskill']:25} {weak['accuracy']:6.1%}")
    
    diag_count = len(hist['diagnostics']) if hist and hist.get('diagnostics') else 0
    print(f"\nDiagnostic History: {diag_count} sessions")
    if diag_count > 0:
        for diag in hist['diagnostics']:
            print(f"  - {diag['sessionId']}: {diag['estimatedCefr']} ({diag['totalCorrect']}/{diag['totalAttempts']} = {diag['accuracy']:.1%})")
            print(f"    Completed: {diag['completedAt']}")
    else:
        print("  (No diagnostic history tracked)")
    
    print("="*80 + "\n")

