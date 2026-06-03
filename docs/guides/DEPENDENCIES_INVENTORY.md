# Dependencies Inventory — Seed Server v5

Дата: 2026-01-12

## Production Dependencies (requirements.txt)

### Core Framework
- **fastapi** `0.110.0` — современный веб-фреймворк для API
- **uvicorn[standard]** `0.29.0` — ASGI сервер с WebSocket и HTTP/2
- **pydantic** `2.6.4` — валидация данных и сериализация

### Configuration & Environment
- **python-dotenv** `1.0.1` — загрузка переменных окружения из .env

### HTTP Client & External APIs
- **httpx** `0.27.0` — async HTTP клиент для LLM провайдеров

### Data Storage & Caching
- **redis** `5.0.8` — Redis клиент для очередей, rate limiting, events, caching

### Monitoring & Observability
- **prometheus-client** `0.20.0` — Prometheus metrics exporter
- **python-json-logger** `2.0.7` — структурированное JSON логирование

### Configuration & Data Formats
- **PyYAML** `6.0.1` — парсинг YAML конфигов (SLO, monitoring)

## Development Dependencies (requirements-dev.txt)

### Code Quality & Linting
- **black** `24.1.1` — code formatter
- **flake8** `7.0.0` — style checker
- **pylint** `3.0.3` — code analysis
- **mypy** `1.8.0` — static type checker
- **isort** `5.13.2` — import sorting

### Testing Framework
- **pytest** `8.0.0` — testing framework
- **pytest-asyncio** `0.23.3` — async test support
- **pytest-cov** `4.1.0` — coverage reporting
- **pytest-mock** `3.12.0` — mocking utilities
- **pytest-timeout** `2.2.0` — test timeouts
- **coverage[toml]** `7.4.0` — code coverage measurement

### Security Scanning
- **bandit[toml]** `1.7.6` — security issue detection
- **safety** `3.0.1` — dependency vulnerability scanning
- **pip-audit** `2.7.0` — audit for known security vulnerabilities
- **detect-secrets** `1.4.0` — secret detection in code

### Advanced Testing
- **mutmut** `2.4.4` — mutation testing для оценки качества тестов

### License & Compliance
- **pip-licenses** `4.3.4` — license checker для зависимостей

### Automation
- **pre-commit** `3.6.0` — pre-commit hooks для автоматизации проверок

## Отсутствующие зависимости (могут потребоваться)

### Load Testing
- `locust` — закомментирован в requirements.txt, для нагрузочного тестирования
- `faker` — закомментирован в requirements.txt, для генерации тестовых данных

### Optional Integrations
- `aioprometheus` — более продвинутые async Prometheus metrics
- `sentry-sdk` — интеграция с Sentry для error tracking
- `opentelemetry-*` — OpenTelemetry для distributed tracing

## Implicit Dependencies (системные)

### Runtime Requirements
- Python 3.10+ (рекомендуется 3.11+)
- Redis 6.0+ для очередей и events
- SQLite 3.35+ (встроен в Python)

### Optional External Services
- OpenAI API (для провайдера openai)
- Google Gemini API (для провайдера gemini)
- Prometheus server (для сбора метрик)
- Grafana (для визуализации метрик)

## Dependency Graph (упрощённый)

```
FastAPI Application
├── uvicorn (ASGI server)
├── pydantic (validation)
├── httpx (LLM API calls)
│   └── OpenAI / Gemini providers
├── redis (queues, events, rate limits)
├── prometheus-client (metrics export)
└── python-json-logger (structured logging)

Testing Stack
├── pytest + plugins
├── coverage
├── security scanners (bandit, safety, pip-audit)
└── code quality (black, flake8, mypy, pylint)
```

## Security Considerations

### Known Vulnerabilities
**Status:** Требуется проверка через `safety check` и `pip-audit`

### License Compliance
**Status:** Требуется проверка через `pip-licenses`

### Update Strategy
- **Critical security patches:** немедленно
- **Minor updates:** ежемесячно
- **Major updates:** после тестирования в staging

## Рекомендуемые действия

### Немедленно
1. Запустить `safety check` для проверки CVE
2. Запустить `pip-audit` для аудита
3. Проверить актуальность версий основных зависимостей

### Регулярно (CI/CD)
1. Автоматическая проверка CVE в каждом PR
2. Dependabot/Renovate для автоматических обновлений
3. Ежемесячный аудит лицензий

### Оптимизация
1. Рассмотреть замену `httpx` на `aiohttp` (если нужна большая производительность)
2. Добавить `orjson` для быстрой JSON сериализации
3. Кеширование зависимостей в Docker образе

## См. также
- [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md) — полная конфигурация сервера
- [SERVER_CAPABILITIES_INVENTORY.md](SERVER_CAPABILITIES_INVENTORY.md) — функции сервера
