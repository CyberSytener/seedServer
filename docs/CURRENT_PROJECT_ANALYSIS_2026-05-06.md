# Current Project Analysis - 2026-05-06

## 2026-05-19 Superseding Note

For current planning, use [SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19.md](SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19.md).

This 2026-05-06 analysis remains useful historical context, but several facts changed or were re-verified on 2026-05-19:

- Route introspection registered `233` routes, not the earlier `226`.
- Focused NeoEats/auth/receipt/cooking backend tests passed with `29 passed`.
- Backend smoke/security/router subset passed with `28 passed`.
- `front-neoeats-snapshot` unit tests passed with `9 passed`, build passed, and smoke flow passed when its mock smoke server was running.
- Public runtime was not healthy during the review: `neoeats.no` and `api.neoeats.no` returned Cloudflare `530`.

## 2026-05-06 NeoEats Addendum

For the latest product outlook, use [PROJECT_OUTLOOK_AND_NEXT_STEPS_2026-05-06.md](PROJECT_OUTLOOK_AND_NEXT_STEPS_2026-05-06.md).

After this analysis was first written, NeoEats public routing, registration, Dashboard and Profile were moved forward:

- `https://neoeats.no/` now serves the frontend, not backend root JSON.
- Registration is open beta style and works through local Vite proxy and public tunnel.
- `GET /api/v1/neoeats/dashboard` aggregates real pantry, receipt and order-saga data.
- `GET/PATCH /api/v1/neoeats/profile` derives profile data from authenticated user metadata, NeoEats memory and real event aggregates.
- The old frontend `UserContext` mock profile was removed from the active app.
- Receipt fallback now fails closed instead of inventing fake line items.
- Public API was rebuilt and mobile Dashboard/Profile smoke passed at `390x844` with no horizontal overflow.

The strategic recommendation has tightened: make NeoEats the primary next product track and use the agent platform as the underlying intelligence layer.

Документ фиксирует фактическое состояние рабочей папки `seed_server/` на 2026-05-06. Это не исторический аудит и не оценка старых фаз, а рабочий срез для продолжения разработки.

## Executive Summary

Seed Server v5 сейчас выглядит как зрелый, но перегруженный backend-монолит с большим количеством доменных вертикалей и уже неплохим тестовым фундаментом. Локально backend собирается, приложение импортируется, основные unit и integration наборы проходят. Архитектурно проект уже ушел дальше раннего MVP: есть агентская платформа, realtime saga engine, Redis-инфраструктура, NeoEats, learning/career/photo домены, marketplace и tenant governance.

Главная проблема сейчас не в том, что система "не работает". Главная проблема в управляемости: рабочее дерево очень грязное, документация фрагментирована и местами устарела, CI, судя по workflow-файлам, не полностью соответствует локальному способу установки зависимостей. Перед новой функциональной фазой нужен короткий stabilization pass.

## Scope

Проверенные области:

- `seed_server/` - основной backend-репозиторий.
- `seed_server/saga-console/` - встроенная React/Vite консоль саг.
- `../front-neoeats-snapshot/` - отдельный NeoEats frontend snapshot без собственного git-репозитория.

Не менялись:

- runtime-код backend/frontend;
- миграции;
- Docker/CI-конфиги;
- секреты и `.env`.

## Repository State

Команды:

```bash
git branch --show-current
git log -1 --oneline --decorate
git worktree list
git status --porcelain=v1
```

Состояние:

- Текущая ветка: `feature/phase0-followup`.
- HEAD: `282cd0d feat(phase7): implement agent sessions P7-08 through P7-17`.
- Worktrees:
  - `seed_server` на `feature/phase0-followup`;
  - `_worktrees/archive-cleanup` на `chore/archive-cleanup-canonical-root`;
  - `_worktrees/code-fixes` на `refactor/code-fixes-baseline`.
- До документационного обновления status показывал примерно:
  - `3151` tracked deletion;
  - `82` modified;
  - `460` untracked.

Вывод: это не release-ready рабочее дерево. Нельзя безопасно начинать крупную фичу, пока не решено, какие удаления и untracked-файлы должны стать частью следующего коммита, а какие являются артефактами.

## Architecture Snapshot

### Backend

Backend построен вокруг `app.main:create_app`.

Основные слои:

- API layer: `app/api/*`, включая auth/admin/jobs/lessons/diagnostics/career/actions/saga/NeoEats/agent/marketplace/console.
- Core layer: `app/core/*`, включая auth/authz, block registry, control-flow blocks, safety, LLM, agent, realtime.
- Services layer: `app/services/*`, включая LLM engine, NeoEats recipe/card/receipt/product flows, marketplace, tenant governance, saga architect.
- Infrastructure layer: `app/infrastructure/*`, включая DB adapters, Redis queues/SSE/usage, middleware, CORS, lifespan, router registration, logging and monitoring.
- Worker layer: `scripts/run_worker.py`, `scripts/run_scheduler.py`, `app/agent_sandbox_worker.py`.

Фактическая route-интроспекция через `create_app()` в test env зарегистрировала `226` маршрутов.

### Data And Runtime

- SQLite остается core DB default через `SEED_DB_PATH`.
- PostgreSQL + pgvector используются для saga/vector-oriented частей при заданных `DATABASE_URL` / `SEED_SAGA_DB_URL`.
- Redis нужен для очередей, SSE/pubsub, rate limits, usage counters и sandbox RPC.
- Alembic содержит 10 миграций, включая webhook subscriptions.
- Docker Compose поднимает `postgres`, `redis`, `api`, `scheduler`, три worker-сервиса, `agent_sandbox` и `sandbox_egress_proxy`.

### Frontends

`seed_server/saga-console`:

- React 18, TypeScript, Vite 6, Zustand, React Flow, Tailwind.
- `npm run build` проходит.
- Тестовых файлов в `saga-console/src` не найдено.

`front-neoeats-snapshot`:

- React 18, Vite 6, Capacitor, Radix UI, TanStack Query, Recharts.
- `npm run build` проходит.
- Найдено 133 TS/TSX файла и 2 test/spec файла.
- Build warning: крупный JS chunk около `1,128 kB` после minification.

## Verification Results

Проверки, выполненные 2026-05-06:

```bash
python -m pytest -q tests/test_ci_smoke.py tests/test_auth_verify_user_context.py tests/unit/test_security_hardening.py tests/unit/test_llm_router_openai_regression.py
```

Результат: `28 passed`.

```bash
python -m pytest -q tests/unit --maxfail=1
```

Результат: `1246 passed, 7 skipped`.

```bash
python -m pytest -q tests/integration --maxfail=1
```

Результат: `64 passed, 2 skipped`.

```bash
cd seed_server/saga-console
npm run build
```

Результат: build passed.

```bash
cd front-neoeats-snapshot
npm run build
```

Результат: build passed, с предупреждением о крупном чанке и смешанном static/dynamic import для Capacitor Camera.

## What Is Strong

- Большой backend test suite локально зеленый.
- Интеграционные agent сценарии уже проходят, включая multi-agent, GitHub fetch demo, tenant demo и WS demo.
- Security-hardening тесты проходят.
- Часть старых audit findings уже закрыта в коде:
  - legacy `X-User-ID` force-disabled in production/public mode;
  - CORS dev mode ограничен localhost/private-network origins, без shared tunnel wildcard;
  - JWT требует непустой secret и whitelist алгоритмов;
  - webhook allowlist больше не содержит `localhost`;
  - AI safety audit fail-closed при отсутствии Gemini client;
  - Redis rate limit использует Lua для atomic increment + expire.
- `app/main.py` уже не выглядит как исходный сверхмонолит на тысячи строк: часть wiring вынесена в infrastructure modules.
- Docker Compose описывает полный runtime, включая sandbox/proxy.

## Main Risks

### P0 - Repository Hygiene

Массовый dirty state делает любой следующий PR трудно проверяемым. Риск: случайно смешать archive cleanup, refactor, feature work и generated artifacts.

Рекомендация: сначала завершить или сбросить scope текущих worktrees по политике из `SOURCE_OF_TRUTH.md`, затем сделать отдельный documentation/stabilization commit.

### P0 - CI Dependency Bootstrap

Workflows `full-tests.yml` и `smoke-tests.yml` ставят:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Но `requirements.txt` содержит только `google-generativeai` и `jsonschema`, а runtime-зависимости backend лежат в `pyproject.toml` и `requirements.lock`. На чистом GitHub runner это выглядит как вероятный CI break.

Рекомендация: заменить установку на один из вариантов:

```bash
pip install -e ".[dev]"
```

или:

```bash
pip install -r requirements.lock
pip install -r requirements-dev.txt
pip install -e . --no-deps
```

### P1 - Documentation Drift

Часть документов содержит старые даты, устаревшие route/test counts и mojibake при чтении в текущей среде. Риск: разработчик будет чинить уже исправленные проблемы или игнорировать актуальные.

Рекомендация: считать текущими только:

- `README.md`;
- `docs/CURRENT_PROJECT_ANALYSIS_2026-05-06.md`;
- `PROBLEMS_AND_TASKS.md`;
- `docs/guides/DOCUMENTATION_INDEX.md`;
- `SOURCE_OF_TRUTH.md`;
- `TASKS.md` как исторический task archive, а не единственный live backlog.

### P1 - Optional Router Failure Visibility

В `app/infrastructure/router_registration.py` блок agent session router все еще ловит широкий `Exception`. Это может скрыть ошибку старта agent API и превратить ее в warning.

Рекомендация: привести к политике остальных router blocks: suppress only `ImportError`, остальные ошибки должны падать на startup или быть явно классифицированы.

### P1 - Production Hardening

Docker Compose и env examples удобны для dev, но требуют отдельного public/prod checklist:

- Redis password/TLS or internal-only guarantee.
- Non-default Postgres credentials.
- Strict `PUBLIC_MODE=1`.
- Non-empty `SEED_ADMIN_KEY`, `SEED_API_KEY_PEPPER`, `JWT_SECRET_KEY`, sandbox secrets.
- Explicit `ALLOWED_ORIGINS`.
- Worker/sandbox health strategy.

### P1 - Frontend Test And Bundle Risk

`saga-console` build проходит, но тестов в source tree нет. NeoEats snapshot build проходит, но есть большой chunk и очень небольшая test surface.

Рекомендация: добавить Vitest/RTL coverage для store, API client, graph/blueprint mappers и critical UI flows; затем сделать chunk split для NeoEats camera/cooking/vision flows.

### P2 - Exception Surface

По `Select-String` найдено около `738` вхождений `except Exception` в `app`. Часть из них оправдана как boundary handling, но масштаб затрудняет observability.

Рекомендация: не переписывать все сразу. Начать с API/router boundaries, worker loop, LLM provider boundaries и sandbox RPC.

## Recommended Development Plan

### Phase 1 - Stabilization

Цель: сделать repo and CI trustworthy.

1. Разделить текущий dirty state на понятные группы: archive cleanup, code fixes, docs, generated artifacts.
2. Исправить CI dependency bootstrap.
3. Добавить CI jobs для уже зеленых локально команд:
   - smoke tests;
   - unit tests;
   - integration tests;
   - `saga-console npm run build`.
4. Пометить устаревшие документы как historical или перенести в archive.

### Phase 2 - Production Readiness

Цель: безопасно открыть систему наружу.

1. Harden Redis/Postgres/secrets in Compose/public docs.
2. Убрать broad exception suppression in router registration.
3. Добавить worker/sandbox heartbeat health checks.
4. Зафиксировать public deployment checklist как blocking gate.

### Phase 3 - Product Focus

Выбрать один главный продуктовый трек, иначе платформа будет расползаться.

Рекомендуемый порядок:

1. NeoEats MVP: inventory, receipt vision, cooking plan, orders, public frontend.
2. Agent platform: sessions, sandbox, tool permissions, marketplace billing.
3. Learning/career domains: только после стабилизации shared LLM/eval слой.

### Phase 4 - Quality And Observability

1. Сократить broad exception surface в самых горячих boundary modules.
2. Добавить structured logs для saga/agent/user request correlation.
3. Ввести минимальные frontend tests.
4. Добавить bundle budget для NeoEats frontend.
5. Добавить route inventory generation в docs/CI, чтобы OpenAPI/README не дрейфовали.

## Bottom Line

Проект уже достаточно силен технически, чтобы продолжать как платформу, а не как прототип. Но следующий правильный шаг - не новая крупная фича, а короткое наведение порядка: git hygiene, CI bootstrap, prod hardening gates и консолидация документации. После этого лучше выбрать один продуктовый трек, вероятнее NeoEats или Agent Platform, и вести его до end-to-end production readiness.
