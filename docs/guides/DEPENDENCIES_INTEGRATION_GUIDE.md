# 🔧 ПОЛНОЕ РУКОВОДСТВО ЗАВИСИМОСТЕЙ И ПОДКЛЮЧЕНИЯ

## Содержание
1. [Python зависимости](#python-зависимости)
2. [Внешние сервисы](#внешние-сервисы)
3. [Переменные окружения](#переменные-окружения)
4. [Локальная установка](#локальная-установка)
5. [Docker setup](#docker-setup)
6. [Интеграция с клиентом](#интеграция-с-клиентом)
7. [Troubleshooting](#troubleshooting)

---

## Python зависимости

### Основные производственные зависимости (`requirements.txt`)

```
Версия Python: 3.9+
```

| Пакет | Версия | Назначение | Статус |
|-------|--------|-----------|--------|
| **FastAPI** | 0.110.0 | Web framework | ✅ Обязателен |
| **Uvicorn** | 0.29.0 | ASGI server | ✅ Обязателен |
| **Pydantic** | 2.6.4 | Data validation | ✅ Обязателен |
| **httpx** | 0.27.0 | Async HTTP client для LLM | ✅ Обязателен |
| **redis** | 5.0.8 | Job queue, caching | ✅ Обязателен |
| **python-dotenv** | 1.0.1 | .env файлы | ✅ Обязателен |
| **prometheus-client** | 0.20.0 | Метрики | ✅ Обязателен |
| **python-json-logger** | 2.0.7 | JSON логирование | ✅ Обязателен |
| **PyYAML** | 6.0.1 | SLO config parsing | ✅ Обязателен |

### Опциональные зависимости (для локальной разработки)

```bash
pip install -r requirements-dev.txt
```

| Пакет | Версия | Назначение |
|-------|--------|-----------|
| **pytest** | 8.0.0 | Unit тестирование |
| **pytest-asyncio** | 0.23.3 | Async test support |
| **pytest-cov** | 4.1.0 | Code coverage |
| **black** | 24.1.1 | Code formatting |
| **flake8** | 7.0.0 | Linting |
| **mypy** | 1.8.0 | Type checking |
| **isort** | 5.13.2 | Import sorting |
| **bandit** | 1.7.6 | Security scanning |
| **safety** | 3.0.1 | Dependency security |
| **pip-audit** | 2.7.0 | Audit trail |
| **detect-secrets** | 1.4.0 | Secret scanning |

### Версионирование

- **Strict:** Все production версии точные (==)
- **Dev:** Dev пакеты на ~= (compatible release)
- **Python:** 3.9+ (tested on 3.11, 3.12)

### Команда установки

```bash
# Production setup
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Development setup
pip install -r requirements-dev.txt

# Verify installation
python -c "import fastapi, redis, httpx; print('✅ All core imports successful')"
```

---

## Внешние сервисы

### 🗄️ Redis (КРИТИЧЕСКИ ВАЖЕН)

**Версия:** 7+  
**Порт:** 6379  
**Контроль:** Job queue, caching, SSE coordination

#### Установка

**Docker (рекомендуется):**
```bash
docker run -d \
  --name seed_redis \
  -p 6379:6379 \
  redis:7-alpine \
  redis-server --appendonly yes
```

**Linux/MacOS:**
```bash
# Homebrew
brew install redis
brew services start redis

# Check
redis-cli ping  # Should return PONG
```

**Windows:**
```powershell
# Docker Desktop (рекомендуется)
docker pull redis:7-alpine
docker run -d -p 6379:6379 redis:7-alpine

# Или WSL: wsl --install ubuntu-22.04
# sudo apt install redis-server
```

#### Проверка подключения

```bash
# Check if running
redis-cli ping
# Expected: PONG

# Check version
redis-cli info server | grep redis_version
# Expected: redis_version:7.x.x

# Check connectivity from Python
python -c "import redis; r = redis.Redis(); r.ping(); print('✅ Connected')"
```

#### Configuration

```yaml
# docker-compose.yml (уже установлено)
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  command: ["redis-server", "--appendonly", "yes"]
  volumes:
    - redis_data:/data
```

### 📊 SQLite Database

**Файл:** `seed.db` (автоматически создается)  
**Формат:** WAL mode (Write-Ahead Logging)  
**Размер:** ~50MB для production

#### Инициализация

```bash
# Автоматическая при первом запуске
# app/db.py создает schema при connect

# Manual check
sqlite3 seed.db ".tables"
# Expected: users, plans, sessions, etc.
```

#### Backup

```bash
# Backup database
cp seed.db seed.db.backup.$(date +%Y%m%d_%H%M%S)

# Backup с WAL файлами
cp seed.db seed.db-shm seed.db-wal backup/
```

### 🤖 LLM API Keys

#### OpenAI

```env
OPENAI_API_KEY=sk-...
SEED_OPENAI_MODEL_FAST=gpt-4-turbo  # Or gpt-3.5-turbo
SEED_OPENAI_MODEL_BATCH=gpt-4       # More expensive, for batch jobs
SEED_OPENAI_BASE_URL=https://api.openai.com/v1  # Optional
```

**Ссылка:** https://platform.openai.com/api-keys  
**Стоимость:** ~$0.01-0.03 per 1K tokens

#### Google Gemini

```env
GEMINI_API_KEY=AIza...
SEED_GEMINI_MODEL_FAST=gemini-pro        # Fast model
SEED_GEMINI_MODEL_BATCH=gemini-1.5-pro   # Batch mode
SEED_GEMINI_BASE_URL=https://generativelanguage.googleapis.com  # Optional
```

**Ссылка:** https://ai.google.dev/  
**Стоимость:** Бесплатно до 60 запросов/минуту

#### Выбор провайдера

```python
# app/settings.py выбирает провайдера автоматически
# Порядок приоритета:
# 1. Если SEED_PROVIDER=openai -> OpenAI
# 2. Если SEED_PROVIDER=gemini -> Gemini
# 3. Если оба установлены -> Gemini (по умолчанию)
# 4. Если ни один -> Error at startup
```

### 🔗 Optional External Services

| Сервис | Назначение | Обязательный | Ссылка |
|--------|-----------|------------|--------|
| OpenAI | LLM provider | ❌ (если Gemini) | api.openai.com |
| Google Gemini | LLM provider | ❌ (если OpenAI) | ai.google.dev |
| Sentry | Error tracking | ❌ | sentry.io |
| Datadog | Monitoring | ❌ | datadog.com |

---

## Переменные окружения

### Шаблон (`template/.env.example`)

```bash
cp .env.example .env
# Отредактировать .env с реальными значениями
```

### 📝 Полный список переменных

#### Database
```env
SEED_DB_PATH=./seed.db  # SQLite file path
```

#### Redis
```env
SEED_REDIS_URL=redis://localhost:6379/0
SEED_REDIS_NAMESPACE=seed  # Prefix for all keys
```

#### API Keys (SECURITY)
```env
# CRITICAL: Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
SEED_ADMIN_KEY=<strong-random-key>
SEED_ADMIN_API_KEY=seed_<random>

# Additional security
SEED_API_KEY_PEPPER=<strong-random-key>  # Hash salt
```

#### LLM Configuration
```env
# One of these MUST be set
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...

# Model selection
SEED_OPENAI_MODEL_FAST=gpt-4-turbo
SEED_OPENAI_MODEL_BATCH=gpt-4
SEED_GEMINI_MODEL_FAST=gemini-pro
SEED_GEMINI_MODEL_BATCH=gemini-1.5-pro

# Optional overrides
SEED_OPENAI_BASE_URL=https://api.openai.com/v1
SEED_GEMINI_BASE_URL=https://generativelanguage.googleapis.com

# Provider selection
SEED_PROVIDER=gemini  # or openai
```

#### Rate Limiting & Plans
```env
SEED_DEFAULT_PLAN=free  # or pro, premium
SEED_FAST_TIMEOUT_SEC=3  # Fast model timeout
SEED_MAX_INPUT_CHARS_DEFAULT=12000
SEED_MAX_OUTPUT_CHARS_DEFAULT=20000
```

#### CORS Configuration
```env
SEED_DEV_CORS=1  # 1 = any localhost:*, null origin (dev)
                 # 0 = use SEED_CORS_ORIGINS (prod)
SEED_CORS_ORIGINS=https://app.example.com,https://app2.example.com
```

#### System Configuration
```env
SEED_EMERGENCY_MODE=0  # 1 to disable new signups
SEED_METRICS_ENABLED=1  # 1 to enable Prometheus
SEED_OPTIMIZE_MODE=false  # Optimization features
SEED_PROMPT_TEST_MODE=false  # A/B test mode
```

#### Logging
```env
SEED_LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
SEED_JSON_LOGGING=1  # 1 for JSON logs
```

#### Optional Services
```env
SENTRY_DSN=  # For error tracking
DATADOG_API_KEY=  # For monitoring
```

### 🔒 Генерация секретных ключей

```python
# script: generate_secrets.py
import secrets

admin_key = secrets.token_urlsafe(32)
api_key_pepper = secrets.token_urlsafe(32)

print(f"SEED_ADMIN_KEY={admin_key}")
print(f"SEED_API_KEY_PEPPER={api_key_pepper}")

# Output example:
# SEED_ADMIN_KEY=xyz1234...
# SEED_API_KEY_PEPPER=abc5678...
```

**Или в командной строке:**
```bash
# Unix/Linux/MacOS
python -c "import secrets; print('SEED_ADMIN_KEY=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('SEED_API_KEY_PEPPER=' + secrets.token_urlsafe(32))"

# PowerShell
python -c "import secrets; print('SEED_ADMIN_KEY=' + secrets.token_urlsafe(32))"
```

---

## Локальная установка

### Prerequisites
- Python 3.9+
- Redis 7+
- Git

### Пошаговая установка

#### 1️⃣ Клонировать репозиторий

```bash
git clone <repo-url> seed.server
cd seed.server
```

#### 2️⃣ Создать virtual environment

```bash
# Unix/Linux/MacOS
python3 -m venv venv
source venv/bin/activate

# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1
```

#### 3️⃣ Установить зависимости

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Для development
```

#### 4️⃣ Настроить окружение

```bash
# Копировать шаблон
cp .env.example .env

# Отредактировать .env (добавить ключи API)
# Minimal required:
# - OPENAI_API_KEY или GEMINI_API_KEY
# - SEED_ADMIN_KEY
# - SEED_API_KEY_PEPPER
```

#### 5️⃣ Запустить Redis

```bash
# Docker (рекомендуется)
docker run -d -p 6379:6379 redis:7-alpine

# Или локально
redis-server
```

#### 6️⃣ Инициализировать базу данных

```bash
# Автоматическая при первом запуске
# Или manual:
python -c "from app.db import get_db; db = get_db(); print('✅ DB initialized')"
```

#### 7️⃣ Запустить сервер

```bash
# Вариант 1: All-in-one (для development)
python run.py

# Вариант 2: Separate processes (для production)
# Terminal 1: API
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2: Scheduler
python run_scheduler.py

# Terminal 3-5: Workers
python run_worker.py --queue q_fast --name fast
python run_worker.py --queue q_batch --name batch
python run_worker.py --queue q_low --name low
```

#### 8️⃣ Проверить установку

```bash
# Check API
curl http://localhost:8000/health
# Expected: {"ok": true, "redis": true, ...}

# Check logs
python check_production_ready.py
# Should show ✅ for all checks
```

---

## Docker setup

### 🐳 Полная сборка

```bash
# Build & start everything
docker-compose up --build

# In background
docker-compose up -d --build

# View logs
docker-compose logs -f api
docker-compose logs -f worker_fast

# Stop
docker-compose down

# Full cleanup
docker-compose down -v
docker system prune -a
```

### 📦 Структура Docker Compose

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  api:
    build: .  # Dockerfile in root
    ports:
      - "8000:8000"
    depends_on:
      - redis
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

  scheduler:
    build: .
    depends_on:
      - redis
    command: ["python", "run_scheduler.py"]

  worker_fast:
    build: .
    depends_on:
      - redis
    command: ["python", "run_worker.py", "--queue", "q_fast", "--name", "fast"]

  worker_batch:
    # Similar configuration

  worker_low:
    # Similar configuration

volumes:
  seed_data:  # Persistent database
  redis_data:  # Persistent Redis
```

### 🔧 Кастомизация Docker

**Использовать собственный Redis:**
```yaml
# docker-compose.yml
redis:
  image: redis:7  # Full version instead of alpine
  volumes:
    - ./redis.conf:/usr/local/etc/redis/redis.conf
  command: redis-server /usr/local/etc/redis/redis.conf
```

**Production-ready Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Интеграция с клиентом

### 🎨 Web Frontend (React/Vue)

#### Базовый пример

```javascript
// 1. Получить список персон
const response = await fetch('http://localhost:8000/v1/personas');
const personas = await response.json();
// [{id: 'classic_tutor', name: 'Classic Tutor', ...}, ...]

// 2. Создать пользователя
const user = await fetch('http://localhost:8000/v1/users', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    user_id: 'user123',
    email: 'user@example.com'
  })
});
const {api_key} = await user.json();
// Сохранить api_key в localStorage

// 3. Использовать для всех запросов
const headers = {
  'Authorization': `Bearer ${api_key}`,
  'Content-Type': 'application/json'
};

// 4. Запустить диагностику
const diag = await fetch(
  'http://localhost:8000/v1/learning/diagnostic/start',
  {
    method: 'POST',
    headers,
    body: JSON.stringify({
      native_lang: 'English',
      target_lang: 'Spanish'
    })
  }
);
const session = await diag.json();
// {session_id, items: [{id, content, type}], ...}

// 5. Streaming для уроков
const eventSource = new EventSource(
  'http://localhost:8000/v1/lessons/generate/stream',
  {
    method: 'POST',
    headers,
    body: JSON.stringify({...})
  }
);
eventSource.addEventListener('progress', (e) => {
  const {bytes_received} = JSON.parse(e.data);
  updateProgressBar(bytes_received);
});
```

### 🖥️ Desktop Client (Electron/Tauri)

```javascript
// Similar but with local file:// protocol
const ipcMain = require('electron').ipcMain;

ipcMain.handle('api:call', async (event, endpoint, options) => {
  const response = await fetch(
    `http://localhost:8000${endpoint}`,
    {
      ...options,
      headers: {
        ...options.headers,
        'Authorization': `Bearer ${getStoredApiKey()}`
      }
    }
  );
  return response.json();
});

// IPC usage
const result = await ipcRenderer.invoke('api:call', '/v1/users', {
  method: 'POST',
  body: JSON.stringify({user_id, email})
});
```

### 📱 Mobile (React Native)

```javascript
// Using fetch API (built-in)
import AsyncStorage from '@react-native-async-storage/async-storage';

const getApiKey = async () => {
  return await AsyncStorage.getItem('api_key');
};

const apiCall = async (endpoint, options = {}) => {
  const apiKey = await getApiKey();
  const response = await fetch(
    `http://192.168.1.100:8000${endpoint}`,  // Use local IP, not localhost
    {
      ...options,
      headers: {
        ...options.headers,
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json'
      }
    }
  );
  return response.json();
};

// Usage
const user = await apiCall('/v1/users', {
  method: 'POST',
  body: JSON.stringify({user_id: 'mobile_user', email})
});
```

### 🔐 CORS Configuration

**Development (localhost):**
```env
SEED_DEV_CORS=1  # Allows any localhost:*, null origin
```

**Production:**
```env
SEED_DEV_CORS=0
SEED_CORS_ORIGINS=https://app.example.com,https://staging.example.com
```

**CORS headers добавляются автоматически:**
```
Access-Control-Allow-Origin: *  (dev) или specific origins (prod)
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization
```

---

## Troubleshooting

### 🔴 Проблема: `ModuleNotFoundError: No module named 'fastapi'`

**Решение:**
```bash
# Убедитесь что venv активирован
source venv/bin/activate  # Unix/Linux/MacOS
.\venv\Scripts\Activate.ps1  # Windows

# Переустановить
pip install -r requirements.txt
```

### 🔴 Проблема: `ConnectionRefusedError: [Errno 111] Connection refused` (Redis)

**Решение:**
```bash
# Проверить Redis
redis-cli ping
# Если not running:

# Docker
docker run -d -p 6379:6379 redis:7-alpine

# Или локально
redis-server
```

### 🔴 Проблема: `sqlite3.OperationalError: database is locked`

**Решение:**
```bash
# WAL mode может заблокировать файл
# Удалить lock файлы
rm seed.db-shm seed.db-wal
rm seed.db  # If severely corrupted

# Restart API
python run.py
```

### 🔴 Проблема: `OPENAI_API_KEY not found`

**Решение:**
```bash
# Проверить .env file
cat .env | grep OPENAI_API_KEY

# Или Gemini
cat .env | grep GEMINI_API_KEY

# Добавить ключ
echo "OPENAI_API_KEY=sk-..." >> .env
```

### 🔴 Проблема: `workers not processing jobs`

**Решение:**
```bash
# Убедитесь что worker processes запущены
# Terminal 1: API (порт 8000)
python run.py

# Terminal 2: Scheduler
python run_scheduler.py

# Terminal 3: Workers (or docker-compose)
python run_worker.py --queue q_fast --name fast

# Проверить job queue
redis-cli KEYS "seed:*"
redis-cli LRANGE seed:q_fast 0 -1
```

### 🟡 Проблема: `WARNING: No LLM API keys configured`

**Решение:**
```bash
# Нужно установить OpenAI или Gemini
# Проверить .env
echo "OPENAI_API_KEY=sk-..." >> .env
# Или
echo "GEMINI_API_KEY=AIza..." >> .env

# Restart
python run.py
```

### 🟡 Проблема: High memory usage

**Решение:**
```python
# app/settings.py - уменьшить pool sizes
HTTP_POOL_LIMITS = {
    "max_connections": 50,  # default: 100
    "max_keepalive_connections": 10,  # default: 20
}

# Or reduce worker count
# docker-compose.yml - remove worker_low
```

### 🟢 Проблема: `localhost:8000 refused to connect`

**Решение:**
```bash
# Проверить что API запущен
curl http://localhost:8000/health

# Если не работает, проверить порт
netstat -tlnp | grep 8000  # Unix
netstat -ano | findstr :8000  # Windows

# Занято? Изменить порт
python -m uvicorn app.main:app --port 8001
```

---

## 📊 Чек-лист интеграции

### ☐ Backend Setup
- ☐ Python 3.9+ установлен
- ☐ pip install requirements.txt завершен
- ☐ Redis 7+ запущен
- ☐ .env файл создан и заполнен
- ☐ API запущен на localhost:8000
- ☐ Scheduler и workers запущены

### ☐ API Verification
- ☐ GET /health возвращает `{ok: true}`
- ☐ GET /v1/personas возвращает список
- ☐ POST /v1/users создает user + возвращает api_key
- ☐ POST /v1/learning/diagnostic/start работает
- ☐ POST /v1/lessons/generate/stream возвращает SSE

### ☐ Client Setup
- ☐ Frontend/Desktop app подключается к localhost:8000
- ☐ CORS headers позволяют запросы
- ☐ API key хранится и отправляется в Authorization header
- ☐ Endpoints работают с реальными данными
- ☐ Streaming события получаются и обрабатываются

### ☐ Monitoring
- ☐ GET /metrics возвращает Prometheus metrics
- ☐ Logs записываются в stdout/файл
- ☐ Database создана с правильной schema
- ☐ Redis connection активна

---

## 🎯 Next Steps

1. **Установить:** Следовать локальной установке выше
2. **Тестировать:** Запустить check_production_ready.py
3. **Интегрировать:** Подключить клиент используя примеры
4. **Мониторировать:** Настроить alerts в slo_config.yaml
5. **Продакшн:** Использовать docker-compose для deployment

---

**Версия:** 2026-01-12  
**Для вопросов:** Смотреть FULL_SYSTEM_AUDIT_2026.md
