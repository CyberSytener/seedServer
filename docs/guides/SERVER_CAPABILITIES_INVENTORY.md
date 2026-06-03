# Инвентаризация функций сервера — Seed Server v5

Дата: 2026-01-12

Ниже собран полный список основных возможностей сервера, доступных в текущем кодовой базе.

1) Базовая инфраструктура и диагностика
- Эндпойнты: `/health`, корень `/`.
- Настройка CORS (dev/prod), метрики Prometheus (`/metrics` при включении).
- Инициализация SQLite, Redis, seed defaults, persona loader, feature flags, performance monitor, key audit tables.

2) LLM Action Router
- Эндпойнт: `POST /v1/actions` — маршрутизация действий (ask, fix, translate, summarize и т.д.).
- Политики планов, rate-limiting, проверка квот, inline fast execution или постановка в очередь.
- Провайдеры: OpenAI, Gemini, Stub — подсчёт токенов, возврат cost/persona.

3) Пользователи и управление ключами
- `POST /v1/users` — создание пользователя и выдача API-ключа (admin-проверки для is_admin).
- `POST /v1/keys/rotate`, `POST /v1/admin/keys/{user_id}/rotate`, `POST /v1/admin/keys/{user_id}/revoke`, audit.
- `GET /v1/limits` — информация о плане и потреблении.

4) События и стримы (SSE)
- `GET /v1/stream` — подписка на события пользователя (job_queued, job_running, job_done, job_failed, job_cancelled).
- SSE для генерации уроков/диагностик и статусов job'ов.

5) Очереди задач и фоновая обработка
- `POST /v1/jobs/submit`, `GET /v1/jobs/status/{job_id}`, `GET /v1/jobs/status/{job_id}/stream`, `GET /v1/jobs/list`, `POST /v1/jobs/{job_id}/cancel`.
- Redis-backed queues: `q_fast`, `q_batch`, `q_low`, приоритеты, scheduling, оценка ожидаемого времени.

6) Генерация уроков и система оценивания
- `POST /v1/lessons/generate` — синхронная генерация урока (валидируется и сохраняется в БД).
- `POST /v1/lessons/submit` — отправка ответа, оценка, хранение попытки и генерация summary.
- Список/получение/удаление уроков: `GET /v1/lessons`, `GET /v1/lessons/{lesson_id}`, `DELETE /v1/lessons/{lesson_id}`.
- Streaming: `POST /v1/lessons/generate/stream` (SSE прогресс и финальный JSON).

7) Диагностическая система (placement & adaptive)
- `POST /v1/diagnostics/generate` — генерация набора diagnostic items.
- Специализированные тесты: `POST /v1/diagnostics/specialized/{test_type}` (business, medical, academic, technical, dialects).
- Клиент V1 сессии: `/v1/learning/diagnostic/start`, `/v1/learning/diagnostic/attempt`, `/v1/learning/diagnostic/next`, `/v1/learning/diagnostic/finish`.
- Streaming: `POST /v1/diagnostics/generate/stream` (SSE по каждому item).

8) Learning Path — Blueprint Pattern
- `/v1/path/unit/generate_blueprint` — Phase A: генерирует blueprint Unit (nodes метаданные).
- `/v1/path/node/start` — Phase B: ставит job на генерацию контента node; сохраняет job_id.
- Управление нодами/юнитами: список, детали, submit node attempt (`/v1/path/node/submit`) — расчёт звёзд, разблокировка следующей ноды.
- Аналитика по пользователю и нодам, рекомендации и адаптация.

9) Профили и планы обучения
- Learning profile: `GET /v1/learning/profile`, `POST /v1/learning/profile/upsert`, `PATCH /v1/learning/profile`.
- Генерация learning plan: `POST /v1/learning/plan/generate` — возвращает план + firstLessonRequest.

10) Personas
- `GET /v1/personas` — список доступных персон с метаданными; файловая загрузка persona prompts.

11) Prompt testing (опционально)
- Подключаемый модуль при `SEED_PROMPT_TEST_MODE`: `api/prompt-testing/*` — запуск сессий тестирования промптов, обзор результатов, управление baseline/test prompts.

12) Bug reports / Feedback
- `POST /v1/feedback/bug-reports` — приём структурированных отчётов, нормализация и сохранение.

13) Мониторинг, SLO и админ-инструменты
- Performance snapshot: `/v1/monitoring/performance` (p50/p95/p99, токены, операции) — admin.
- Health/degradation check: `/v1/monitoring/health` — admin.
- SLO: `/v1/monitoring/slo` и `/v1/monitoring/slo/{slo_name}/history` — admin.
- Metrics router: `/v1/metrics/prometheus` и `/v1/metrics/summary`.

14) Feature flags и A/B тесты
- `GET /v1/feature-flags`, toggle `/v1/feature-flags/{flag_name}/toggle` — admin.
- A/B тесты: `POST /v1/ab-tests/run`, `GET /v1/ab-tests/{test_id}/summary` — admin.

15) Rate limiting и админ-управление
- Runtime rate-limiter в критичных местах (actions, diagnostics, lesson generation).
- Admin эндпоинты: `GET /v1/admin/rate-limits/{user_id}`, reset и cleanup.

16) Alerting и аудиты
- Endpoints для просмотра/решения алертов `/v1/admin/alerts*`.
- Key audit tables, key rotation и аудит событий.

17) Интеграции и зависимости
- Redis: очереди, события, rate limits, usage counters.
- OpenAI / Gemini провайдеры для LLM; Stub provider для тестов/CI.
- Prometheus-compatible metrics output.

18) Хранилище данных
- SQLite схемы для users, jobs, lessons, attempts, diagnostic_sessions/items, learning_profiles/plans, units/nodes, feature_flags, key_audit, performance, alerts, bug_reports.

Как использовать (минимальные шаги)
- Создать пользователя: `POST /v1/users` → получить `api_key`.
- Узнать лимиты: `GET /v1/limits`.
- Быстрый action: `POST /v1/actions` (режим `fast` пытается выполнить inline, иначе очередь).
- Длинные задачи: `POST /v1/jobs/submit` + `GET /v1/jobs/status/{id}/stream`.
- Диагностика: `POST /v1/learning/diagnostic/start` → attempts → next → finish.
- Уроки: `POST /v1/lessons/generate` или `POST /v1/lessons/generate/stream` → `POST /v1/lessons/submit`.

Где смотреть исходники
- Основной FastAPI entry: `app/main.py`.
- LLM router / провайдеры: `app/router.py`, `app/llm/*`.
- Jobs / Queue: `app/job_queue_api.py`, `app/queue_redis.py`, `app/sse_redis.py`.
- Lesson/Diagnostic/Path modules: `app/lesson_*`, `app/diagnostic_*`, `app/path_api.py`.

## См. также

Полная инвентаризация сервера:
- **[COMPLETE_INVENTORY_INDEX.md](COMPLETE_INVENTORY_INDEX.md)** — навигация по всем документам инвентаризации
- **[CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md)** — все environment variables и конфигурация
- **[DEPENDENCIES_INVENTORY.md](DEPENDENCIES_INVENTORY.md)** — зависимости с версиями и CVE-проверкой
- **[TEST_SUITE_INVENTORY.md](TEST_SUITE_INVENTORY.md)** — структура тестов и coverage
- **[../openapi.json](../openapi.json)** — OpenAPI спецификация (65 endpoints, 90 schemas)
