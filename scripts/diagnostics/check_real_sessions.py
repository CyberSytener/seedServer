from app.infrastructure.db.sqlite import DB
import json

db = DB('./seed.db')

# Посмотрим на реальные языковые пары (исключая тестовые)
sessions = db.fetchall('''
    SELECT id, user_id, native_lang, target_lang, status, created_at
    FROM diagnostic_sessions
    WHERE native_lang NOT IN ('Русский', 'упячка')
    AND target_lang NOT IN ('Мемы', 'Python', 'Русский')
    ORDER BY created_at DESC
    LIMIT 10
''')

print('Реальные диагностические сессии (без тестовых данных):')
print('=' * 80)
for s in sessions:
    session_id = s['id'][:16]
    user_id = s['user_id'][:20]
    langs = f"{s['native_lang']}→{s['target_lang']}"
    status = s['status']
    created = s['created_at'][:19]
    print(f'{session_id} | {user_id} | {langs} | {status} | {created}')

total = db.fetchone('SELECT COUNT(*) as count FROM diagnostic_sessions')['count']
print(f'\nВсего сессий: {total}')
print(f'Реальных сессий: {len(sessions)}')

# Посмотрим на уникальные языковые пары
pairs = db.fetchall('''
    SELECT native_lang, target_lang, COUNT(*) as count
    FROM diagnostic_sessions
    WHERE native_lang NOT IN ('Русский', 'упячка')
    AND target_lang NOT IN ('Мемы', 'Python', 'Русский')
    GROUP BY native_lang, target_lang
    ORDER BY count DESC
''')

print('\nУникальные языковые пары:')
for p in pairs:
    print(f"  {p['native_lang']} → {p['target_lang']}: {p['count']} сессий")
