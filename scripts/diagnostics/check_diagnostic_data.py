from app.infrastructure.db.sqlite import DB
import json

db = DB('./seed.db')

# Получить последние 10 попыток
rows = db.fetchall('''
    SELECT session_id, item_id, answer_raw, is_correct, response_time_ms,
           tags_snapshot_json, created_at
    FROM diagnostic_attempts
    ORDER BY created_at DESC
    LIMIT 10
''')

print('Последние 10 попыток диагностики:')
print('=' * 120)
print(f"{'session_id':<15} {'item_id':<10} {'answer_raw':<25} {'correct':<8} {'time_ms':<10} {'tags':<40} {'created_at'}")
print('-' * 120)

for row in rows:
    session_id = row['session_id'][:14]
    item_id = row['item_id'][:9]
    answer = row['answer_raw'][:24] if row['answer_raw'] else 'None'
    correct = str(row['is_correct'])
    time_ms = str(row['response_time_ms']) if row['response_time_ms'] else 'None'
    tags = row['tags_snapshot_json'][:39] if row['tags_snapshot_json'] else 'None'
    created = row['created_at'][:19]

    print(f"{session_id:<15} {item_id:<10} {answer:<25} {correct:<8} {time_ms:<10} {tags:<40} {created}")

print('\nПроверка наличия данных:')
print(f"Всего попыток: {db.fetchone('SELECT COUNT(*) as count FROM diagnostic_attempts')['count']}")

# Проверить, сколько попыток имеют response_time_ms
time_count = db.fetchone('SELECT COUNT(*) as count FROM diagnostic_attempts WHERE response_time_ms IS NOT NULL')['count']
print(f"Попыток с временем реакции: {time_count}")

# Проверить, сколько попыток имеют tags
tags_count = db.fetchone('SELECT COUNT(*) as count FROM diagnostic_attempts WHERE tags_snapshot_json IS NOT NULL AND tags_snapshot_json != \"\"')['count']
print(f"Попыток с тегами навыков: {tags_count}")

# Проверить сессии
sessions = db.fetchall('SELECT id, user_id, native_lang, target_lang, status FROM diagnostic_sessions ORDER BY created_at DESC LIMIT 5')
print(f"\nПоследние 5 сессий:")
for s in sessions:
    print(f"  {s['id'][:16]} | {s['user_id'][:20]} | {s['native_lang']}→{s['target_lang']} | {s['status']}")
