from app.infrastructure.db.sqlite import DB
import json

db = DB('./seed.db')
rows = db.fetchall('SELECT user_id, profile_json FROM learning_profiles')

profiles_with_diagnostics = []
for row in rows:
    profile = json.loads(row['profile_json'])
    hist = profile.get('history')
    diag_count = len(hist.get('diagnostics', [])) if hist else 0
    if diag_count > 0:
        profiles_with_diagnostics.append((row['user_id'], diag_count, profile))

print(f'Найдено профилей с диагностикой: {len(profiles_with_diagnostics)}')
for user_id, diag_count, profile in profiles_with_diagnostics[:3]:
    print(f'User: {user_id} - Диагностик: {diag_count} - CEFR: {profile.get("estimatedCefr")} - {profile.get("nativeLanguage")}→{profile.get("targetLanguage")}')
