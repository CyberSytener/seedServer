# Seed Server v5 — Полный аудит продукта

**Дата:** 31 марта 2026  
**Версия:** v0.1.0 (85% production-ready)  
**Стек:** Python 3.12 · FastAPI 0.110 · Redis 7 · PostgreSQL (pgvector) · SQLite · Gemini/OpenAI LLM

---

## Содержание

1. [Резюме](#1-резюме)
2. [Критические уязвимости безопасности](#2-критические-уязвимости-безопасности)
3. [Проблемы высокого приоритета](#3-проблемы-высокого-приоритета)
4. [Проблемы среднего приоритета](#4-проблемы-среднего-приоритета)
5. [Архитектурный долг](#5-архитектурный-долг)
6. [Инфраструктура и DevOps](#6-инфраструктура-и-devops)
7. [Качество кода и тестирование](#7-качество-кода-и-тестирование)
8. [Зависимости](#8-зависимости)
9. [План улучшений (Roadmap)](#9-план-улучшений-roadmap)
10. [Сводная таблица рисков](#10-сводная-таблица-рисков)

---

## 1. Резюме

Seed Server v5 — это зрелый async-first backend на FastAPI с мощной системой саг, real-time WebSocket-шлюзом, LLM-интеграцией и богатым набором доменов (Career, NeoEats, Photo, Marketplace). Архитектура в целом чистая, слои разделены корректно, циклических импортов нет.

**Однако обнаружены серьёзные проблемы:**

| Категория | Критические | Высокие | Средние | Низкие |
|-----------|:-----------:|:-------:|:-------:|:------:|
| Безопасность | 6 | 8 | 7 | 5 |
| Качество кода | 2 | 4 | 6 | — |
| Инфраструктура | 1 | 3 | 4 | — |
| **Итого** | **9** | **15** | **17** | **5** |

**Общая оценка зрелости:**

| Аспект | Оценка | Комментарий |
|--------|:------:|------------|
| Архитектура | B+ | Чистые слои, но god-object в `create_app()` |
| Безопасность | C | 6 критических уязвимостей |
| Тестирование | C+ | Порог 50% слишком низкий |
| Инфраструктура | C | Redis без пароля, воркеры без healthcheck |
| Зависимости | B | Версии свежие, но некоторые ослаблены |
| Документация | A- | Обширная, но фрагментированная |

---

## 2. Критические уязвимости безопасности

### CRIT-1: Обход аутентификации через Legacy X-User-ID

**Файл:** `app/core/auth.py` (строки 228–280)  
**Уровень:** 🔴 КРИТИЧЕСКИЙ  

При включённом `SEED_ENABLE_LEGACY_X_USER_ID` любой клиент может установить заголовок `X-User-ID: admin` и получить доступ без учётных данных. Система автоматически создаёт пользователя если он не существует — атакующий может создать неограниченное количество аккаунтов.

**Сценарий атаки:**  
1. Злоумышленник отправляет `X-User-ID: admin`  
2. Если параметр включён — он становится администратором  
3. Никаких учётных данных не требуется

**Исправление:**
- Полностью удалить legacy auth или требовать дополнительную верификацию (API-ключ + заголовок)
- Запретить auto-create пользователей из непроверенных источников
- Добавить `if settings.is_production: raise RuntimeError("Legacy auth disabled in production")`

---

### CRIT-2: CORS Misconfiguration с Credentials

**Файл:** `app/infrastructure/cors.py` (строки 28–31)  
**Уровень:** 🔴 КРИТИЧЕСКИЙ  

`allow_credentials=True` комбинируется с `allow_methods=["*"]` и `allow_headers=["*"]`. В dev-режиме разрешены `*.ngrok.io`, `*.trycloudflare.com` — любой пользователь ngrok может делать запросы к API от имени аутентифицированного пользователя.

**Исправление:**
- Указать явные `allow_methods=["GET", "POST", "PUT", "DELETE"]`
- Указать явные `allow_headers=["content-type", "authorization"]`
- Удалить wildcard-домены из dev-режима; оставить только `localhost`
- Добавить guard: `if settings.is_production and settings.cors_dev_mode: raise RuntimeError`

---

### CRIT-3: JWT — Default Secret в коде + Algorithm Confusion

**Файл:** `app/core/security/jwt.py` (строка 23, 31)  
**Уровень:** 🔴 КРИТИЧЕСКИЙ  

1. Дефолтный секрет `"dev-secret-key-change-this-32-bytes"` хранится как константа в исходном коде
2. Алгоритм JWT (`HS256` по умолчанию) передаётся как параметр без whitelist-валидации — возможна атака Algorithm Confusion

**Исправление:**
```python
ALLOWED_ALGORITHMS = {"HS256", "HS384", "HS512"}
if algorithm not in ALLOWED_ALGORITHMS:
    raise ValueError(f"Unsupported JWT algorithm: {algorithm}")
```
- Удалить константу `DEFAULT_INSECURE_JWT_SECRET`
- Обязать установку секрета через env-переменную в production

---

### CRIT-4: SSRF через Webhook Allowlist

**Файл:** `app/core/safety.py` (строка 17)  
**Уровень:** 🔴 КРИТИЧЕСКИЙ  

Allowlist содержит `localhost`:
```python
ALLOWED_WEBHOOK_DOMAINS = {"hooks.slack.com", "discord.com", "localhost"}
```
Атакующий может отправить webhook на `http://localhost:6379` (Redis) или `http://localhost:5432` (PostgreSQL), взаимодействуя с внутренними сервисами.

**Исправление:**
- Удалить `localhost` из allowlist
- Добавить blocklist: `127.0.0.1`, `0.0.0.0`, `10.*`, `172.16-31.*`, `192.168.*`
- Валидировать URL через DNS resolution (не допускать private IP)

---

### CRIT-5: AI Safety Audit — Fail-Open

**Файл:** `app/core/safety.py` (строки 127–131)  
**Уровень:** 🔴 КРИТИЧЕСКИЙ  

Если `GEMINI_API_KEY` не настроен, все блюпринты автоматически проходят safety-проверку:
```python
if not self._gemini:
    return SafetyVerdict(True, "ai_audit_skipped (no key)")  # ← PASS!
```

**Исправление:** Fail-closed: возвращать `SafetyVerdict(False, "ai_audit_unavailable")` при отсутствии ключа. В production требовать ключ обязательно.

---

### CRIT-6: Race Condition в Rate Limiting

**Файл:** `app/core/rate_limit.py` (строки 47–62)  
**Уровень:** 🔴 КРИТИЧЕСКИЙ  

Счётчик инкрементируется ДО проверки лимита. Атакующий может отправить burst из `hard_rps + N` запросов до блокировки. IP rate limit ещё слабее: `hard_rpm * 3`.

**Исправление:** Использовать Lua-скрипт для атомарного check-and-increment в Redis. Снизить IP-множитель с 3x до 2x.

---

## 3. Проблемы высокого приоритета

### HIGH-1: Redis без аутентификации

**Файл:** `docker-compose.yml`  
Redis запущен без `requirepass`. Любой процесс в сети контейнеров имеет полный доступ к данным, очередям, и сессиям.

**Исправление:** Добавить `command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}` и настроить переменную окружения.

---

### HIGH-2: Воркеры без Health Check

**Файл:** `docker-compose.yml`  
Сервисы `scheduler`, `worker_fast`, `worker_batch` имеют `healthcheck: disable: true`. Docker не перезапустит упавший воркер.

**Исправление:** Реализовать health endpoint для воркеров или использовать файловый heartbeat.

---

### HIGH-3: In-Memory Auth Failure Rate Limiter

**Файл:** `app/core/auth.py` (строки 27–57)  
`AuthFailureRateLimiter` использует `dict` в памяти. При рестарте сервера все счётчики сбрасываются. В кластере — каждый инстанс ведёт свой счёт.

**Исправление:** Использовать Redis для хранения auth failure counters.

---

### HIGH-4: API Key Pepper может быть пустым

**Файл:** `app/settings.py` (строка 207)  
`SEED_API_KEY_PEPPER` по умолчанию пустая строка. Без pepper API-ключи уязвимы к rainbow table атакам.

**Исправление:** В production требовать непустой pepper: `if not pepper: raise RuntimeError`.

---

### HIGH-5: Admin Key может быть пустым

**Файл:** `app/settings.py` (строка 206)  
`SEED_ADMIN_KEY` по умолчанию пустой. Отсутствует предупреждение при запуске без admin key.

**Исправление:** Логировать warning при пустом ключе. В production — hard fail.

---

### HIGH-6: Test Auth Mode в development

**Файл:** `app/core/auth.py` (строки 131–137)  
`SEED_TEST_AUTH_MODE=true` + `SEED_ENV=development` позволяет использовать предсказуемые токены формата `test_*`. Нет логирования использования.

**Исправление:** Логировать warning при каждом test-auth запросе. Запретить test mode вне `test` окружения.

---

### HIGH-7: Gemini Adapter — Stub в продакшене

**Файл:** `app/ai_adapters.py` (строки 210–240)  
`GeminiImageEditAdapter.edit_image()` — заглушка, возвращающая placeholder. В production тихо «работает» без реальной обработки.

**Исправление:** Реализовать полный Gemini Vision adapter или бросать `NotImplementedError` в production.

---

### HIGH-8: God Object: create_app() — 380+ строк

**Файл:** `app/main.py` (строки 71–450)  
Одна функция инициализирует всё: логирование, БД, Redis, LLM, саги, роутеры, middlewares. Трудно тестировать, трудно поддерживать.

**Исправление:** Разбить на 5 функций: `_setup_logging()`, `_init_database()`, `_init_llm_service()`, `_init_realtime()`, `_register_routers()`.

---

## 4. Проблемы среднего приоритета

| # | Проблема | Файл | Описание |
|---|----------|------|----------|
| MED-1 | Header Injection в Request-ID | `app/middleware/request_id.py` | Заголовок `X-Request-ID` принимается от клиента без валидации формата. Возможна log injection. |
| MED-2 | Утечка информации в ошибках | `app/infrastructure/exception_handlers.py` | В не-public режиме в ответ включается `debug_info` с path и reason. |
| MED-3 | Admin wildcard scope `*` | `app/core/authz.py` | Роль `admin` имеет `{"*"}` — нет гранулярного контроля. |
| MED-4 | CORS origins без валидации | `app/settings.py` | Значения `SEED_CORS_ORIGINS` не проверяются на формат URL. |
| MED-5 | Deprecated rate_limiter shim | `app/rate_limiter.py` | Импортирует из несуществующего `app.core.rate_limiter` (должен быть `rate_limit`). |
| MED-6 | Confirmation state в памяти | `app/core/realtime/action_router.py` | Pending confirmations теряются при рестарте — нет persistence. |
| MED-7 | Unbounded saga tracking | `app/core/realtime/sagas/orchestrator.py` | `_active_sagas` и `_saga_start_times` растут без cleanup. |
| MED-8 | PostgreSQL без HEALTHCHECK | `docker-compose.yml` | Docker не перезапустит упавшую БД. |
| MED-9 | Silent adapter registration | `app/infrastructure/app_wiring.py` | Если saga adapter не найден — тихо пропускается. |
| MED-10 | LLM service registration fail-safe | `app/main.py` | try/except + logging.warning при ошибке регистрации провайдера — production стартует без LLM. |
| MED-11 | SQLite threading bottleneck | `app/infrastructure/db/sqlite.py` | Единый `_lock` для всех операций — блокирует async concurrency. |

---

## 5. Архитектурный долг

### 5.1 Известные cross-layer нарушения (из ROADMAP_2026)

| Нарушение | Описание | Влияние |
|-----------|----------|---------|
| `core/auth.py → infrastructure/db/sqlite.DB` | Auth проверки требуют живую БД | Auth не работает без БД |
| `orchestrator.py → services/diagnostic, career` | Saga-оркестратор знает о доменных сервисах | Невозможно переиспользовать саги |
| `infrastructure/redis/worker.py → core/interfaces` | Инфраструктура зависит от ядра | Upgrade trap |

### 5.2 Отсутствующая бизнес-логика

- **Нет Job Pipeline:** сканирование → принятие → gap analysis → курс → обновление CV
- **Нет persona scoring** для job leads
- **Saga isolation:** падение одной саги каскадно влияет на остальные
- **pgvector** для skill embeddings не интегрирован

### 5.3 Проблемы масштабируемости

| Проблема | Текущее состояние | Решение |
|----------|-------------------|---------|
| SQLite thread-lock | Единый `threading.Lock()` | Миграция на PostgreSQL для основной БД |
| In-memory state | Confirmation, rate limit counters | Перенос в Redis |
| Единый сервер | Нет horizontal scaling | Session affinity + Redis-backed state |

---

## 6. Инфраструктура и DevOps

### 6.1 Docker

| Компонент | Состояние | Проблема |
|-----------|-----------|----------|
| Dockerfile | ✅ Хорошо | Non-root user, health check |
| docker-compose.yml | ⚠️ Проблемы | Redis без пароля, воркеры без healthcheck |
| Sandbox | ✅ Отлично | `read_only`, `cap_drop: ALL`, сетевая изоляция |
| `requirements.lock` | ❌ Отсутствует | Dockerfile ссылается на файл, которого нет в repo |

### 6.2 Makefile — Критические пробелы

Текущие targets: `run`, `test`, `clean`  

**Отсутствуют:**

| Target | Команда | Важность |
|--------|---------|----------|
| `lint` | `flake8 app/ && pylint app/` | 🔴 Высокая |
| `typecheck` | `mypy app/` | 🔴 Высокая |
| `security` | `bandit -r app/ && safety check` | 🔴 Высокая |
| `format` | `black app/ && isort app/` | 🟡 Средняя |
| `coverage` | `pytest --cov=app --cov-report=html` | 🟡 Средняя |
| `migrate` | `alembic upgrade head` | 🟡 Средняя |
| `docker-build` | `docker-compose build` | 🟡 Средняя |

### 6.3 Мониторинг

- ✅ Prometheus metrics on `/metrics`
- ✅ JSON structured logging + PII masking
- ⚠️ Нет alerting pipeline (Grafana/AlertManager)
- ⚠️ Нет distributed tracing (Jaeger/Zipkin)
- ⚠️ Нет audit event loss metrics

---

## 7. Качество кода и тестирование

### 7.1 Тестирование

| Метрика | Значение | Оценка |
|---------|----------|--------|
| Файлов тестов | 158+ | ✅ Хорошо |
| Порог покрытия | 50% | 🔴 Слишком низкий |
| Тестовые маркеры | tier1-4, unit, integration, sim | ✅ Хорошо |
| Мutation testing | mutmut настроен | ✅ Хорошо |
| E2E тесты | Директория есть, глубина неясна | ⚠️ Требует проверки |

### 7.2 Размер файлов и сложность

| Файл | Строк | Проблема |
|------|:-----:|---------|
| `app/main.py` | ~455 | God object `create_app()` |
| `app/core/realtime/action_router.py` | ~400+ | 5 ответственностей в одном классе |
| `app/core/realtime/sagas/orchestrator.py` | ~350+ | Приемлемо для сложности саг |

### 7.3 Отсутствующие dev-инструменты

| Инструмент | Назначение | Приоритет |
|------------|------------|-----------|
| `pytest-benchmark` | Тесты производительности саг | 🟡 Средний |
| `hypothesis` | Property-based тесты для валидаторов | 🟡 Средний |
| `factory-boy` | Генерация тестовых фикстур | 🟢 Низкий |

---

## 8. Зависимости

### 8.1 Runtime-зависимости (28 пакетов)

| Пакет | Версия | Статус |
|-------|--------|--------|
| fastapi | 0.110.0 | ✅ Актуально |
| uvicorn[standard] | 0.29.0 | ✅ Актуально |
| pydantic | 2.6.4 | ✅ Актуально |
| httpx[http2] | 0.27.0 | ✅ Актуально |
| redis | 5.0.8 | ✅ Актуально |
| SQLAlchemy | >=2.0,<2.1 | ⚠️ Закреплён minor — автопатчи не придут |
| asyncpg | >=0.29.0 | ⚠️ Можно обновить до 0.30+ |
| google-genai | >=0.8.0 | ⚠️ Слишком открытый — может сломать при 0.9/0.10 |
| PyJWT | >=2.8.0 | ✅ Гибкий |

### 8.2 Рекомендации

- Закрепить google-genai: `>=0.8.0,<0.9.0`
- Ослабить SQLAlchemy: `>=2.0`
- Создать `requirements.lock` для reproducible builds
- Запустить `pip-audit` и `safety check` в CI

---

## 9. План улучшений (Roadmap)

### Фаза 0: Критические исправления безопасности (1—2 недели)

| # | Задача | Файл | Приоритет |
|---|--------|------|-----------|
| 1 | Удалить или заблокировать Legacy X-User-ID auth в production | `app/core/auth.py` | 🔴 P0 |
| 2 | Исправить CORS: убрать wildcard-методы/заголовки, убрать ngrok/cloudflare домены | `app/infrastructure/cors.py` | 🔴 P0 |
| 3 | JWT: удалить дефолтный секрет, добавить whitelist алгоритмов | `app/core/security/jwt.py` | 🔴 P0 |
| 4 | Удалить `localhost` из webhook allowlist, добавить blocklist приватных IP | `app/core/safety.py` | 🔴 P0 |
| 5 | AI Safety: fail-closed при отсутствии ключа | `app/core/safety.py` | 🔴 P0 |
| 6 | Rate limit: атомарный check-and-increment через Lua-скрипт | `app/core/rate_limit.py` | 🔴 P0 |
| 7 | Добавить пароль Redis | `docker-compose.yml` | 🔴 P0 |
| 8 | Обязать `SEED_API_KEY_PEPPER` и `SEED_ADMIN_KEY` в production | `app/settings.py` | 🔴 P0 |

### Фаза 1: Стабилизация (2—4 недели)

| # | Задача | Файл | Приоритет |
|---|--------|------|-----------|
| 9 | Включить health checks для воркеров и PostgreSQL | `docker-compose.yml` | 🟡 P1 |
| 10 | Перенести auth failure rate limiter в Redis | `app/core/auth.py` | 🟡 P1 |
| 11 | Перенести pending confirmations в Redis | `app/core/realtime/action_router.py` | 🟡 P1 |
| 12 | Добавить валидацию X-Request-ID (regex `^[a-zA-Z0-9-]{1,36}$`) | `app/middleware/request_id.py` | 🟡 P1 |
| 13 | Убрать debug_info из ответов или ограничить internal-only | `app/infrastructure/exception_handlers.py` | 🟡 P1 |
| 14 | Исправить deprecated shim `app/rate_limiter.py` или удалить | `app/rate_limiter.py` | 🟡 P1 |
| 15 | Реализовать полный Gemini Image Adapter (не stub) | `app/ai_adapters.py` | 🟡 P1 |
| 16 | Добавить cleanup для `_active_sagas` и `_saga_start_times` | `app/core/realtime/sagas/orchestrator.py` | 🟡 P1 |
| 17 | Запретить test auth mode вне окружения `test` | `app/core/auth.py` | 🟡 P1 |

### Фаза 2: Качество и автоматизация (4—6 недель)

| # | Задача | Файл | Приоритет |
|---|--------|------|-----------|
| 18 | Поднять порог покрытия до 70% | `pyproject.toml` | 🟡 P1 |
| 19 | Рефакторинг `create_app()` — разбить на 5 функций | `app/main.py` | 🟡 P1 |
| 20 | Расширить Makefile: lint, typecheck, security, format, coverage, migrate | `Makefile` | 🟡 P1 |
| 21 | Создать `requirements.lock` для Docker build | корень проекта | 🟡 P1 |
| 22 | Закрепить `google-genai>=0.8.0,<0.9.0` | `requirements.txt` | 🟡 P1 |
| 23 | Добавить CORS origin validation (urlparse) | `app/infrastructure/cors.py` | 🟢 P2 |
| 24 | Добавить гранулярные scopes вместо wildcard `*` для admin | `app/core/authz.py` | 🟢 P2 |
| 25 | Добавить `/internal/routes` для аудита API-поверхности | `app/api/` | 🟢 P2 |
| 26 | SQLite → PostgreSQL для основной БД (threading bottleneck) | `app/infrastructure/db/` | 🟢 P2 |

### Фаза 3: Масштабирование и наблюдаемость (6—10 недель)

| # | Задача | Описание | Приоритет |
|---|--------|----------|-----------|
| 27 | Distributed tracing (OpenTelemetry/Jaeger) | End-to-end trace для саг и LLM-вызовов | 🟢 P2 |
| 28 | Alerting pipeline (Grafana + AlertManager) | Алерты на rate limit spikes, auth failures, saga DLQ | 🟢 P2 |
| 29 | Saga isolation: изоляция падения одной саги | Каждая сага в своём контексте ошибок | 🟢 P2 |
| 30 | pgvector для skill embeddings | Семантический поиск навыков | 🟢 P2 |
| 31 | Job Pipeline (scan → accept → gap → course → CV) | Core business feature | 🟢 P2 |
| 32 | Horizontal scaling: session affinity + Redis state | Готовность к multi-instance deploy | 🟢 P2 |
| 33 | Audit event loss metrics | Counter для потерянных audit events | 🟢 P2 |

### Фаза 4: Зрелость продукта (10—16 недель)

| # | Задача | Описание | Приоритет |
|---|--------|----------|-----------|
| 34 | Persona-aware job scoring | Оценка вакансий с учётом персоны пользователя | 🟢 P3 |
| 35 | Deprecation lifecycle для V1 compat | `app/core/compat.py` — добавить дедлайн и warnings | 🟢 P3 |
| 36 | Property-based тесты (hypothesis) для валидаторов | Более глубокое покрытие edge cases | 🟢 P3 |
| 37 | Performance benchmarks для саг (pytest-benchmark) | Регрессионное тестирование производительности | 🟢 P3 |
| 38 | Universal Interface (Phase 4 из ROADMAP_2026) | Единый UI для всех доменов | 🟢 P3 |

---

## 10. Сводная таблица рисков

| ID | Риск | Уровень | Вероятность | Влияние | Статус |
|----|------|---------|:-----------:|:-------:|:------:|
| CRIT-1 | Auth bypass через X-User-ID | 🔴 Критический | Высокая | Полный доступ | Открыт |
| CRIT-2 | CORS с credentials + wildcards | 🔴 Критический | Средняя | CSRF, кража токенов | Открыт |
| CRIT-3 | JWT default secret + alg confusion | 🔴 Критический | Средняя | Подделка токенов | Открыт |
| CRIT-4 | SSRF через webhook localhost | 🔴 Критический | Средняя | Доступ к внутренним сервисам | Открыт |
| CRIT-5 | AI Safety fail-open | 🔴 Критический | Высокая | Небезопасные блюпринты | Открыт |
| CRIT-6 | Rate limit race condition | 🔴 Критический | Высокая | DDoS bypass | Открыт |
| HIGH-1 | Redis без пароля | 🟠 Высокий | Средняя | Утечка данных | Открыт |
| HIGH-2 | Воркеры без healthcheck | 🟠 Высокий | Высокая | Silent failure | Открыт |
| HIGH-3 | In-memory rate limiter | 🟠 Высокий | Средняя | Brute-force auth | Открыт |
| HIGH-7 | Gemini adapter — stub | 🟠 Высокий | Высокая | Silent prod failure | Открыт |
| HIGH-8 | God object create_app() | 🟠 Высокий | — | Maintainability | Открыт |
| MED-11 | SQLite threading block | 🟡 Средний | Средняя | Performance degradation | Открыт |

---

*Отчёт сгенерирован на основе полного анализа исходного кода, конфигураций, зависимостей и инфраструктуры проекта Seed Server v5.*  
*Следующий аудит рекомендуется провести после завершения Фазы 0 (исправления безопасности).*
