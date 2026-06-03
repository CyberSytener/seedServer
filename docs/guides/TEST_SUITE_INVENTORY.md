# Test Suite Inventory — Seed Server v5

Дата: 2026-01-12

## Обзор тестов

Всего найдено: **28 тестовых файлов**

### Unit Tests (tests/unit/)
- `test_bug_report.py` — тесты bug report системы
- `test_bug_report_compat.py` — обратная совместимость bug reports
- `test_diagnostic.py` — unit тесты диагностической системы
- `test_diagnostic_async.py` — async тесты диагностики

### Integration Tests (tests/integration/)
- `test_learning_path_simple.py` — интеграционные тесты learning path
- `test_end_to_end_flow.py` — полный end-to-end flow
- `test_async_endpoints.py` — async endpoint тесты
- `test_placement_simple.py` — simple placement тесты
- `test_placement_proof.py` — proof-of-concept placement
- `test_placement_eng_spanish.py` — англ-испанский placement

### Root Level Tests (tests/)
- `test_load_blueprint.py` — загрузка blueprint
- `test_adaptive_learning.py` — адаптивное обучение
- `test_ci_smoke.py` — smoke тесты для CI
- `test_api.py` — общие API тесты
- `test_auth_flows.py` — аутентификация flows
- `test_diagnostic_session.py` — diagnostic session логика
- `test_translate_validation.py` — валидация переводов
- `test_rate_limiter.py` — rate limiter тесты
- `test_diagnostic_simple.py` — простые диагностические тесты
- `conftest.py` — pytest fixtures и конфигурация

### PowerShell Tests (tests/powershell/)
Около **18 PowerShell тестовых скриптов** для ручного/интеграционного тестирования:
- `test_client_v1.ps1`
- `test_desktop_client_compat.ps1`
- `test_bug_report_quick.ps1`
- `test_production_simple.ps1`
- `test_production_baseline.ps1`
- `test_lesson_generation_auth.ps1`
- `test_learning_plan.ps1`
- и другие...

## Тестовое покрытие (оценка)

**Статус:** Требуется запуск pytest с coverage для точных цифр

### Покрываемые модули
- ✅ Diagnostic system (unit + integration)
- ✅ Bug reports (unit + compat)
- ✅ Authentication flows
- ✅ Rate limiting
- ✅ Learning path
- ✅ Async endpoints
- ✅ End-to-end flows
- ✅ Translation validation
- ✅ Adaptive learning

### Не покрытые или требующие больше тестов
- ⚠️ Lesson generation (только PowerShell интеграционные)
- ⚠️ Job queue system
- ⚠️ Personas API
- ⚠️ Metrics/SLO monitoring
- ⚠️ Feature flags
- ⚠️ A/B testing
- ⚠️ Alerting system
- ⚠️ Key management (rotation, audit)

## Запуск тестов

### Требования
```bash
# Установить dev dependencies
pip install -r requirements-dev.txt
```

### Команды

#### Все тесты
```bash
pytest tests/ -v
```

#### С покрытием
```bash
pytest tests/ --cov=app --cov-report=term --cov-report=html
```

#### Только unit
```bash
pytest tests/unit/ -v
```

#### Только integration
```bash
pytest tests/integration/ -v
```

#### CI smoke test
```bash
pytest tests/test_ci_smoke.py -v
```

#### Конкретный тест
```bash
pytest tests/test_diagnostic_session.py::test_create_session -v
```

### PowerShell тесты
```powershell
# Запустить конкретный тест
.\tests\powershell\test_client_v1.ps1

# Запустить все PS тесты
Get-ChildItem tests\powershell\*.ps1 | ForEach-Object { & $_.FullName }
```

## Тестовые данные

### Fixtures (tests/conftest.py)
- Database fixtures (test DB setup/teardown)
- Mock Redis clients
- Test user credentials
- Sample lesson/diagnostic data

### Data Files (data/test/)
- `test_items.json` — тестовые diagnostic items
- `test_diagnostic_request.json` — примеры запросов
- `lesson_generation_comparison.json` — сравнения генерации
- `lesson_response.json` — примеры ответов
- `test_optimize_lesson_response.json` — оптимизированные ответы

### Baseline Data (data/baseline/)
- `baseline_items.json` — baseline diagnostic items
- `baseline_items_v2.json` — v2 baseline
- `learning_taxonomy_v0_1.json` — таксономия обучения

## Рекомендуемые улучшения

### Немедленно
1. Настроить виртуальное окружение
2. Установить dev dependencies
3. Запустить полный test suite с coverage
4. Исправить failing tests

### Краткосрочно (1-2 недели)
1. Добавить тесты для lesson generation API
2. Добавить тесты для job queue system
3. Покрыть тестами metrics/monitoring endpoints
4. Настроить CI/CD pipeline с автоматическим запуском тестов

### Среднесрочно (1-2 месяца)
1. Достичь 80%+ code coverage
2. Добавить mutation testing (mutmut)
3. Настроить property-based testing (hypothesis)
4. Добавить performance/load tests (locust)

### Долгосрочно
1. E2E тесты с реальными LLM провайдерами
2. Contract testing для API
3. Chaos engineering тесты
4. Security penetration testing

## CI/CD Integration

### Рекомендуемая конфигурация
```yaml
# .github/workflows/test.yml (пример)
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      redis:
        image: redis:7
        ports:
          - 6379:6379
    
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      
      - name: Run tests
        run: pytest tests/ --cov=app --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## См. также
- [DEPENDENCIES_INVENTORY.md](DEPENDENCIES_INVENTORY.md) — список зависимостей
- [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md) — конфигурация
- [SERVER_CAPABILITIES_INVENTORY.md](SERVER_CAPABILITIES_INVENTORY.md) — функции сервера
