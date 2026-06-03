# API Key Management System

## Обзор

Система управления API-ключами обеспечивает полный жизненный цикл ключей с audit trail и admin-контролем.

## Возможности

### 🔑 Ротация ключей (Self-Service)

Пользователи могут самостоятельно ротировать свои ключи:

```bash
POST /v1/keys/rotate
Headers:
  X-API-Key: <current_key>

Response:
{
  "new_api_key": "seed_...",
  "message": "API key rotated successfully"
}
```

**Важно:** После ротации старый ключ немедленно инвалидируется.

### 🔒 Отзыв ключей (Admin)

Администраторы могут отозвать ключи пользователей:

```bash
POST /v1/admin/keys/{user_id}/revoke
Headers:
  X-Admin-Key: <admin_key>
Body:
{
  "reason": "security_incident"
}

Response:
{
  "status": "success",
  "message": "API key revoked"
}
```

### 🔄 Admin-ротация ключей

Администраторы могут ротировать ключи других пользователей:

```bash
POST /v1/admin/keys/{user_id}/rotate
Headers:
  X-Admin-Key: <admin_key>

Response:
{
  "new_api_key": "seed_...",
  "user_id": "...",
  "message": "API key rotated successfully"
}
```

### 📊 Audit Log

Просмотр истории операций с ключами:

```bash
GET /v1/admin/keys/{user_id}/audit
Headers:
  X-Admin-Key: <admin_key>

Response:
{
  "events": [
    {
      "event_type": "revocation",
      "user_id": "user123",
      "key_last4": "abcd",
      "reason": "security_incident",
      "actor": "admin",
      "timestamp": "2024-01-10T15:30:00Z"
    },
    {
      "event_type": "rotation",
      "user_id": "user123",
      "old_key_last4": "xyz1",
      "new_key_last4": "abc2",
      "actor": "user123",
      "timestamp": "2024-01-10T14:00:00Z"
    }
  ]
}
```

## Безопасность

### Инвалидация ключей

- **Немедленная инвалидация:** При ротации или отзыве ключи инвалидируются мгновенно
- **Проверка в БД:** Каждый запрос проверяет актуальность ключа
- **Нет кэширования:** Ключи не кэшируются, проверка всегда актуальна

### Логирование

Все операции с ключами логируются:

```json
{
  "event": "API key rotated",
  "user_id": "user123",
  "old_key_last4": "xyz1",
  "new_key_last4": "abc2",
  "rotated_by": "user123"
}
```

**Важно:** В логах сохраняются только последние 4 символа ключей.

## Администрирование

### Admin Key Configuration

Установите admin-ключ в `.env`:

```env
SEED_ADMIN_KEY=your-secure-admin-key-here
```

### Использование Admin Endpoints

Все admin endpoints требуют header `X-Admin-Key`:

```bash
curl -X POST http://localhost:8000/v1/admin/keys/user123/revoke \
  -H "X-Admin-Key: your-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"reason": "security_incident"}'
```

## Database Schema

### key_revocations

```sql
CREATE TABLE key_revocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    key_last4 TEXT,
    reason TEXT,
    revoked_by TEXT NOT NULL,
    revoked_at TEXT NOT NULL
);

CREATE INDEX idx_key_revocations_user 
ON key_revocations(user_id, revoked_at DESC);
```

### key_rotations

```sql
CREATE TABLE key_rotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    old_key_last4 TEXT,
    new_key_last4 TEXT NOT NULL,
    rotated_by TEXT NOT NULL,
    rotated_at TEXT NOT NULL
);

CREATE INDEX idx_key_rotations_user 
ON key_rotations(user_id, rotated_at DESC);
```

## Best Practices

### Для пользователей

1. **Регулярная ротация:** Ротируйте ключи каждые 90 дней
2. **Немедленная ротация при утечке:** Если ключ скомпрометирован, ротируйте немедленно
3. **Безопасное хранение:** Никогда не храните ключи в git или публичных местах
4. **Один ключ = один сервис:** Используйте разные ключи для разных сервисов

### Для администраторов

1. **Мониторинг audit log:** Регулярно проверяйте логи на подозрительную активность
2. **Своевременный отзыв:** Отзывайте ключи при увольнении сотрудников или инцидентах
3. **Защита admin-ключа:** Храните admin-ключ в секретном хранилище (Vault, AWS Secrets Manager)
4. **Документирование причин:** Всегда указывайте причину при отзыве ключей

## Testing

Пример комплексного теста (PowerShell):

```powershell
# 1. Создание пользователя
$body = @{user_id="test_user"} | ConvertTo-Json
$user = Invoke-RestMethod -Uri "http://localhost:8000/v1/users" -Method POST -Body $body -ContentType "application/json"
$key1 = $user.api_key

# 2. Ротация ключа
$headers1 = @{ "X-API-Key" = $key1 }
$rotated = Invoke-RestMethod -Uri "http://localhost:8000/v1/keys/rotate" -Method POST -Headers $headers1
$key2 = $rotated.new_api_key

# 3. Проверка: старый ключ не работает
# Должен вернуть 401
$headers1_test = @{ "X-API-Key" = $key1 }
Invoke-RestMethod -Uri "http://localhost:8000/v1/learning/profile" -Method GET -Headers $headers1_test
# Expected: 401 Unauthorized

# 4. Проверка: новый ключ работает
$headers2 = @{ "X-API-Key" = $key2 }
Invoke-RestMethod -Uri "http://localhost:8000/v1/learning/profile" -Method GET -Headers $headers2
# Expected: 200 or 404 (если профиля нет)

# 5. Admin отзыв
$adminHeaders = @{ "X-Admin-Key" = "your-admin-key" }
$revoke_body = @{reason="test"} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/v1/admin/keys/test_user/revoke" -Method POST -Body $revoke_body -ContentType "application/json" -Headers $adminHeaders

# 6. Проверка audit log
$audit = Invoke-RestMethod -Uri "http://localhost:8000/v1/admin/keys/test_user/audit" -Method GET -Headers $adminHeaders
$audit.events  # Должен показать ротацию и отзыв
```

## Troubleshooting

### Проблема: Старый ключ всё ещё работает после ротации

**Причина:** Тестирование на публичных endpoints без аутентификации.

**Решение:** Используйте защищённые endpoints для тестирования:
- ✅ `/v1/learning/profile` (требует auth)
- ✅ `/v1/diagnostic/start` (требует auth)
- ❌ `/v1/personas` (публичный, не требует auth)

### Проблема: Admin endpoints возвращают 401

**Причина:** Неправильный admin-ключ или header.

**Решение:** 
1. Проверьте `.env`: `SEED_ADMIN_KEY=...`
2. Используйте header `X-Admin-Key` (не `X-API-Key`)
3. Перезапустите контейнер после изменения `.env`

### Проблема: Audit log возвращает 500 ошибку

**Причина:** Возможно ошибка в SQL или обработке результатов.

**Решение:**
1. Проверьте логи: `docker-compose logs api --tail=50`
2. Убедитесь, что таблицы созданы (проверится при старте API)
3. Проверьте, что в коде используется `row["field"]` вместо `row.get("field")`

## Integration Examples

### Python Client

```python
import requests

class SeedAPIClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        
    def rotate_key(self) -> str:
        """Rotate API key and return new key."""
        response = requests.post(
            f"{self.base_url}/v1/keys/rotate",
            headers={"X-API-Key": self.api_key}
        )
        response.raise_for_status()
        new_key = response.json()["new_api_key"]
        
        # Update client's key
        self.api_key = new_key
        return new_key
        
    def get_profile(self):
        """Get user profile."""
        response = requests.get(
            f"{self.base_url}/v1/learning/profile",
            headers={"X-API-Key": self.api_key}
        )
        response.raise_for_status()
        return response.json()

# Usage
client = SeedAPIClient("http://localhost:8000", "seed_abc...")
profile = client.get_profile()

# Rotate key every 90 days
new_key = client.rotate_key()
# Save new_key securely (database, secrets manager, etc.)
```

### JavaScript/TypeScript Client

```typescript
class SeedAPIClient {
  constructor(
    private baseUrl: string,
    private apiKey: string
  ) {}
  
  async rotateKey(): Promise<string> {
    const response = await fetch(`${this.baseUrl}/v1/keys/rotate`, {
      method: 'POST',
      headers: {
        'X-API-Key': this.apiKey
      }
    });
    
    if (!response.ok) {
      throw new Error(`Key rotation failed: ${response.statusText}`);
    }
    
    const data = await response.json();
    this.apiKey = data.new_api_key;
    return this.apiKey;
  }
  
  async getProfile() {
    const response = await fetch(`${this.baseUrl}/v1/learning/profile`, {
      headers: {
        'X-API-Key': this.apiKey
      }
    });
    
    if (!response.ok) {
      throw new Error(`Failed to get profile: ${response.statusText}`);
    }
    
    return response.json();
  }
}

// Usage
const client = new SeedAPIClient('http://localhost:8000', 'seed_abc...');
const profile = await client.getProfile();

// Rotate key
const newKey = await client.rotateKey();
// Save newKey securely
```

## Compliance & Auditing

### Regulatory Requirements

Система поддерживает требования:
- **GDPR:** Audit trail всех операций с ключами
- **SOC 2:** Логирование доступа и изменений
- **PCI DSS:** Регулярная ротация ключей (требование 8.2.4)

### Audit Reports

Генерация отчёта по активности пользователя:

```bash
GET /v1/admin/keys/{user_id}/audit

# Фильтруйте результаты в коде:
events = [e for e in audit['events'] if e['event_type'] == 'revocation']
```

### Retention Policy

Рекомендации по хранению audit logs:
- **Минимум:** 90 дней
- **Рекомендуется:** 1 год
- **Для compliance:** 3-7 лет (в зависимости от отрасли)

## Future Enhancements

Планируемые улучшения:

1. **Key Expiration:** Автоматический отзыв ключей после N дней
2. **Key Scopes:** Ограничение прав доступа для разных ключей
3. **IP Whitelisting:** Привязка ключей к IP-адресам
4. **Rate Limiting per Key:** Индивидуальные лимиты для каждого ключа
5. **Webhook Notifications:** Уведомления при ротации/отзыве ключей

## Support

При проблемах с системой управления ключами:

1. Проверьте документацию выше
2. Изучите раздел Troubleshooting
3. Проверьте логи: `docker-compose logs api --tail=100`
4. Откройте issue в репозитории с деталями (логи, steps to reproduce)
