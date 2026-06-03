# Unified Auth And Real LLM Tests

## Что реализовано

- Единый `AuthContext` в `request.state.auth` (best-effort middleware).
- Единые scope-check helpers: `require_scope(...)` / `require_any_scope(...)`.
- Test token режим только при `SEED_TEST_AUTH_MODE=1`.
- Run-level gate для `mode=real` в `/v1/runs`:
  - scope `providers:use:real`,
  - `provider_profile.enabled`,
  - `per_run_cap_units`,
  - `daily_budget_units`.
- Аудит auth решений в `.seed_artifacts/audit/auth_events.jsonl`.

## Test token формат

```
Authorization: Bearer test_<user_id>|<role>|<scope1,scope2,...>
```

Пример:

```
Authorization: Bearer test_sim-user|developer|runs:write,providers:use:real
```

Работает только при:

```
SEED_TEST_AUTH_MODE=1
```

## Provider profiles (runtime)

Профили читаются из `app.state.provider_profiles`.
Если не задано, используется `default_real`.

Пример профиля:

```python
app.state.provider_profiles = {
    "default_real": {
        "id": "default_real",
        "enabled": True,
        "requires_scope": "providers:use:real",
        "daily_budget_units": 500.0,
        "per_run_cap_units": 100.0,
        "allowed_models": ["gpt-4.1-mini"],
        "redaction_policy": {"store_raw_response": False},
    }
}
```

## Как запустить real LLM тест через API

1. Включите test mode:

```bash
SEED_TEST_AUTH_MODE=1
```

2. Создайте/подготовьте flow (`/v1/flows/compile`).

3. Запустите run:

```bash
curl -X POST http://localhost:8000/v1/runs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test_sim-user|developer|runs:write,providers:use:real" \
  -d '{
    "target": {"type":"flow","id":"my_flow"},
    "mode": "real",
    "provider_profile": "default_real",
    "budget": {"requested_units": 1.0},
    "input": {"user_id":"u1","user_request":"hello"}
  }'
```

4. Следите за результатом:

```bash
curl http://localhost:8000/v1/runs/<run_id> \
  -H "Authorization: Bearer test_sim-user|developer|runs:read,providers:use:real"
```
