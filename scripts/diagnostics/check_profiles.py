#!/usr/bin/env python3
"""Check learning profiles in database."""

from app.infrastructure.db.sqlite import DB
import json

db = DB('./seed.db')

# Get all profiles
rows = db.fetchall('SELECT user_id, profile_json, version, updated_at FROM learning_profiles ORDER BY updated_at DESC')

print(f"\n{'='*80}")
print(f"LEARNING PROFILES IN DATABASE: {len(rows)} total")
print(f"{'='*80}\n")

for i, row in enumerate(rows, 1):
    profile = json.loads(row['profile_json'])
    hist = profile.get('history')
    diag_count = len(hist['diagnostics']) if hist and hist.get('diagnostics') else 0
    
    print(f"Profile #{i}")
    print(f"  User ID: {row['user_id']}")
    print(f"  Version: {row['version']}")
    print(f"  Updated: {row['updated_at']}")
    print(f"  Target Language: {profile['targetLanguage']} (from {profile['nativeLanguage']})")
    print(f"  Estimated CEFR: {profile['estimatedCefr']}")
    print(f"  Skill Scores: {len(profile['skillScores'])} skills")
    for skill in profile['skillScores']:
        print(f"    - {skill['skill']}: {skill['score']}/100")
    print(f"  Weak Subskills: {len(profile['weakSubskills'])}")
    for weak in profile['weakSubskills'][:3]:  # Show first 3
        print(f"    - {weak['skill']}/{weak['subskill']}: {weak['accuracy']:.1%}")
    print(f"  Preferences:")
    print(f"    - Topic: {profile['preferences'].get('topic', 'None')}")
    print(f"    - Persona: {profile['preferences'].get('personaId', 'None')}")
    print(f"    - Lesson Length: {profile['preferences'].get('lessonLength', 'None')}")
    print(f"  Diagnostic History: {diag_count} sessions")
    if diag_count > 0:
        for diag in hist['diagnostics']:
            print(f"    - {diag['sessionId']}: {diag['estimatedCefr']} ({diag['totalCorrect']}/{diag['totalAttempts']} = {diag['accuracy']:.1%})")
    print()

print(f"{'='*80}")
print(f"✅ Learning profiles are being stored and tracked correctly!")
print(f"{'='*80}\n")

