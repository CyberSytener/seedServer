# Configuration Reference — Seed Server v5

Дата: 2026-01-12

## Переменные окружения

### Core / Database
- `SEED_DB_PATH` — путь к SQLite файлу (default: `./seed.db`)
- `SEED_DEFAULT_PLAN` — план по умолчанию для новых пользователей (default: `free`)
- `SEED_EMERGENCY_MODE` — аварийный режим: все новые actions в очередь (default: `false`)

### UX / Performance
- `SEED_FAST_TIMEOUT_SEC` — таймаут для inline fast execution (default: `3`)
- `SEED_MAX_INPUT_CHARS_DEFAULT` — максимальная длина input (default: `12000`)
- `SEED_MAX_OUTPUT_CHARS_DEFAULT` — максимальная длина output (default: `20000`)

### Authentication & Security
- `SEED_ADMIN_KEY` — admin ключ для admin операций (default: пустая строка = admin disabled)
- `SEED_API_KEY_PEPPER` — pepper для хеширования API ключей (обязательно в production!)
- `SEED_CACHE_TTL_DAYS` — TTL для кеша (default: `7`)
- `SEED_ENABLE_LEGACY_X_USER_ID` — поддержка legacy заголовка X-User-Id (default: `true`)

### Redis (Queues, Events, Rate Limits)
- `SEED_REDIS_URL` — URL Redis инстанса (default: `redis://localhost:6379/0`)
- `SEED_REDIS_NAMESPACE` — namespace для ключей Redis (default: `seed`)

### Embedded Workers (Dev Mode)
- `SEED_EMBEDDED_WORKERS` — запускать workers внутри API процесса (default: `false`)
- `SEED_EMBEDDED_SCHEDULER` — запускать scheduler внутри API процесса (default: `false`)
- `SEED_EMBEDDED_WORKER_QUEUES` — список очередей для embedded workers (default: `q_fast,q_batch,q_low`)

### LLM Providers
#### Default Provider Selection
- `SEED_DEFAULT_PROVIDER_FAST` — провайдер для fast requests (`openai|gemini|stub`, default: `stub`)
- `SEED_DEFAULT_PROVIDER_BATCH` — провайдер для batch requests (`openai|gemini|stub`, default: `stub`)

#### OpenAI Configuration
- `OPENAI_API_KEY` — OpenAI API key (обязательно если используется OpenAI)
- `SEED_OPENAI_BASE_URL` — базовый URL OpenAI API (default: `https://api.openai.com`)
- `SEED_OPENAI_MODEL_FAST` — модель для fast requests (default: `gpt-4.1-mini`)
- `SEED_OPENAI_MODEL_BATCH` — модель для batch requests (default: `gpt-4.1`)

#### Gemini Configuration
- `GEMINI_API_KEY` — Gemini API key (обязательно если используется Gemini)
- `SEED_GEMINI_BASE_URL` — базовый URL Gemini API (default: `https://generativelanguage.googleapis.com`)
- `SEED_GEMINI_MODEL_FAST` — модель для fast requests (default: `gemini-1.5-flash`)
- `SEED_GEMINI_MODEL_BATCH` — модель для batch requests (default: `gemini-1.5-pro`)

### Rate Limiting (Hard Safety Limits)
- `SEED_HARD_RPM_DEFAULT` — hard limit запросов в минуту (default: `240`)
- `SEED_HARD_RPS_DEFAULT` — hard limit запросов в секунду (default: `20`)

### Metrics & Monitoring
- `SEED_METRICS_ENABLED` — включить Prometheus metrics endpoint (default: `true`)

### CORS
- `SEED_DEV_CORS` — режим dev CORS: разрешает localhost любые порты + null origin (default: `true`)
- `SEED_CORS_ORIGINS` — список разрешённых origins для production, через запятую (default: пусто)

### Feature Flags & Experiments
- `SEED_DEV` — dev режим для persona loader и других модулей (default: `false`)
- `SEED_OPTIMIZE_MODE` — оптимизированный режим генерации (compact output) (default: `false`)
- `SEED_PROMPT_TEST_MODE` — режим A/B тестирования промптов (default: `false`)
- `SEED_PARSER_VERSION` — версия парсера (`baseline|v2`) для performance testing (default: `baseline`)

## Режимы работы

### Development Mode
```bash
SEED_DEV_CORS=true
SEED_DEV=true
SEED_DEFAULT_PROVIDER_FAST=stub
SEED_EMBEDDED_WORKERS=true
SEED_EMBEDDED_SCHEDULER=true
```

### Production Mode
```bash
SEED_DEV_CORS=false
SEED_CORS_ORIGINS=https://app.example.com,https://app2.example.com
SEED_API_KEY_PEPPER=<strong-random-value>
SEED_ADMIN_KEY=<strong-random-value>
SEED_DEFAULT_PROVIDER_FAST=gemini
SEED_DEFAULT_PROVIDER_BATCH=gemini
GEMINI_API_KEY=<your-api-key>
SEED_METRICS_ENABLED=true
SEED_EMBEDDED_WORKERS=false
SEED_EMBEDDED_SCHEDULER=false
```

### Testing Mode
```bash
SEED_DEFAULT_PROVIDER_FAST=stub
SEED_DEFAULT_PROVIDER_BATCH=stub
SEED_REDIS_URL=redis://localhost:6379/15  # Отдельная БД для тестов
SEED_DB_PATH=./test.db
```

## Security Checklist

### Production Must-Haves
- [ ] `SEED_API_KEY_PEPPER` установлен в сильное случайное значение
- [ ] `SEED_ADMIN_KEY` установлен и хранится в secret manager
- [ ] `SEED_DEV_CORS=false` в production
- [ ] `SEED_CORS_ORIGINS` содержит только разрешённые домены
- [ ] Redis защищён password/ACL и доступен только из internal network
- [ ] SQLite файл имеет правильные permissions (600)
- [ ] API keys (OpenAI/Gemini) хранятся в secure secret store

### Рекомендации
- Используйте `.env` файл для локальной разработки
- В production используйте environment variables через orchestrator (k8s secrets, AWS Secrets Manager, etc.)
- Никогда не коммитьте `.env` файлы в git
- Регулярно ротируйте API ключи и секреты
- Мониторьте rate limits и abuse patterns

## См. также
- [SERVER_CAPABILITIES_INVENTORY.md](SERVER_CAPABILITIES_INVENTORY.md) — полный список функций сервера
- [DEPENDENCIES_INVENTORY.md](DEPENDENCIES_INVENTORY.md) — список зависимостей и их версий
