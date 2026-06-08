# Seed Server: сценарий демонстрации портфолио

Этот runbook рассчитан на демонстрацию длительностью 5-8 минут. Он помогает
показать сильные стороны проекта без попытки представить его как полностью
готовый production-продукт.

## Подготовка перед демонстрацией

Требования:

- Python 3.11 или новее;
- Node.js 18 или новее;
- свободный доступ к localhost;
- desktop-браузер с шириной окна не менее 1280px;
- Docker и ключи внешних LLM не требуются.

Один раз установите зависимости:

```powershell
python -m pip install -e ".[dev]"
```

Проверьте проект перед встречей:

```powershell
python scripts/run_portfolio_demo.py --smoke-test --no-open
python scripts/run_quality_gate.py portfolio
python -m pip_audit
Set-Location saga-console
npm audit
npm run build
Set-Location ..
```

Ожидаемый результат: demo smoke завершается строкой `Smoke test passed`,
portfolio gate проходит полностью, dependency audits не находят известных
уязвимостей, Saga Console успешно собирается.

## Запуск демонстрации

Из корня репозитория:

```powershell
python scripts/run_portfolio_demo.py
```

Launcher сам:

- запускает FastAPI backend в безопасном локальном режиме;
- включает детерминированный stub provider;
- выбирает свободные порты;
- запускает Saga Console;
- очищает локальное demo-state для воспроизводимого показа;
- создаёт демонстрационный workflow `market_scan_default`;
- печатает итоговые URL и данные для входа.

Вход:

```text
Username: L0g1n
Password: P@SSW0RD
```

Для остановки нажмите `Ctrl+C` в терминале launcher.

Если нужно сохранить запуски между репетициями:

```powershell
python scripts/run_portfolio_demo.py --keep-state
```

## Сценарий на 5-8 минут

### 1. Сформулируйте проблему

Скажите:

> Большие AI-системы быстро превращаются в монолит: интеграции, промпты,
> бизнес-логика и права доступа начинают зависеть друг от друга. Я исследую
> другой подход: разбивать систему на независимые модули с единым контрактом,
> а AI разрешать предлагать и исправлять модули только внутри контролируемого
> жизненного цикла.

### 2. Покажите Gallery

Откройте `Gallery` и укажите на `market_scan_default`.

Объясните:

- Gallery хранит описания workflow;
- workflow состоит из модулей `market_scanner`, `job_scorer` и
  `notification_block`;
- соединения между ними проверяются по входным и выходным JSON Schema;
- badge `Contract OK` означает, что связи совместимы.

### 3. Покажите Canvas

Нажмите `Open Canvas`.

Объясните:

- Canvas визуализирует контрактный граф;
- модуль объявляет identity, schemas, execution adapter, capabilities,
  зависимости и лимиты;
- core платформы не нужно изменять для каждого нового модуля;
- один и тот же контракт используется UI, валидатором и runtime.

### 4. Покажите Sandbox

Вернитесь в `Gallery`, нажмите `Sandbox`, затем откройте `Runs`.

Объясните:

- sandbox запускает workflow в детерминированном stub-режиме;
- платные LLM и внешние сервисы для демонстрации не нужны;
- результат сохраняет timeline, метрики и выход каждого шага;
- flow run показывает, как несколько модулей исполняются как единый процесс.

### 5. Покажите отдельный Module Run

Откройте `Modules`, выберите `general_assistant` и нажмите `Run Stub`.
Вернитесь в `Runs`.

Объясните:

- модуль можно проверить отдельно до включения в workflow;
- один control plane наблюдает и module runs, и flow runs;
- stub mode делает тесты и демонстрацию воспроизводимыми;
- real mode намеренно выключен в локальной демке, чтобы не требовать секреты.

### 6. Расскажите про безопасное расширение AI

Откройте `docs/PLATFORM_ROADMAP.md` или покажите команды в терминале:

```powershell
seed module create text_normalizer
seed module validate text_normalizer
seed module test text_normalizer
seed module sandbox text_normalizer
seed module qualify text_normalizer
seed module reject text_normalizer --actor reviewer --reason "repair required"
seed module repair-plan text_normalizer --rejection-id REJECTION_ID --json
seed module repair-check text_normalizer --rejection-id REJECTION_ID --actor reviewer
```

Объясните:

- AI не получает право напрямую публиковать код;
- proposal сначала проходит Contract v1, тесты и sandbox;
- rejected candidate сохраняется вместе с diagnostics и подписью;
- `repair-plan` формирует ограниченный context pack;
- допускается не более трёх уникальных repair attempts;
- каждая попытка сохраняет provenance и новый signed snapshot;
- публикация требует отдельного human-gated решения.

## Как система устроена

```text
Saga Console
    -> Console API / control plane
        -> module registry + flow compiler
            -> contract validation
                -> sandbox / saga execution
                    -> run history + evidence

AI or human builder
    -> Module SDK / CLI
        -> validate -> test -> sandbox -> qualify
            -> approve / publish or reject -> bounded repair loop
```

Основные слои:

- `saga-console/`: React/Vite интерфейс оператора;
- `app/api/console/`: API для modules, flows, runs и providers;
- `app/contracts/`: общий контракт модулей;
- `app/module_sdk/`: создание, проверка, evidence и lifecycle;
- `app/core/realtime/sagas/`: orchestration, retries и execution model;
- `modules/`: декларативные модули;
- `tests/`: доказательство поддерживаемого поведения.

## Что важно подчеркнуть

Проект демонстрирует не «ещё один чат с LLM», а инженерную платформу вокруг
AI-кода:

- contract-first расширяемость;
- воспроизводимое локальное исполнение;
- наблюдаемость module и flow runs;
- fail-closed ограничения для secrets и dependencies;
- подписанные evidence и lifecycle decisions;
- bounded repair loop вместо бесконтрольной генерации;
- явное разделение active, candidate, experimental и legacy scope.

## Честные ограничения

Скажите прямо:

- это portfolio demo, а не hosted production SaaS;
- по умолчанию используется stub provider;
- Docker sandbox сильнее subprocess sandbox, но не заменяет VM;
- HMAC доказывает владение общим ключом, но не заменяет public-key identity;
- secret broker, dependency bundle builder и model-provider repair adapter ещё
  находятся в roadmap;
- исторические подсистемы сохранены как исследовательский контекст, но release
  gates относятся только к active scope.

Это не ослабляет проект. Наоборот, показывает умение определять доверенную
границу и не выдавать прототип за production.

## Короткий ответ «что ты сделал сам?»

> Я спроектировал contract-first модель модулей, control plane для modules,
> flows и runs, локальный SDK и CLI, sandbox/evidence lifecycle, подписанные
> publication/rejection decisions, bounded repair loop и Saga Console для
> демонстрации этих механизмов. Также выделил активный scope и настроил
> обязательные CI gates, чтобы широкая экспериментальная кодовая база не
> ломала поддерживаемый portfolio path.

## Возможные вопросы

**Почему Saga, а не простой pipeline?**

Saga-модель даёт основу для длинных процессов, retry, idempotency,
наблюдаемости и будущей compensation-логики. Даже stub demo проходит через
тот же control plane и сохраняет timeline.

**Почему AI не публикует модуль автоматически?**

Генерация и доверие являются разными задачами. AI может предложить или
исправить пакет, но platform policy, sandbox evidence и человек принимают
решение о публикации.

**Что даёт единый контракт?**

Он позволяет валидировать совместимость, строить UI, маршрутизировать
исполнение и формировать repair context из одного декларативного источника.

**Как обеспечивается безопасность?**

Через allowlist зависимостей, capability declarations, subprocess/Docker
sandbox, Python audit hook, fail-closed secret/dependency policy, fingerprints,
подписанные evidence records и отдельный publish gate.

**Что бы вы сделали следующим?**

Добавил бы provider adapter для контролируемого применения repair output,
verified secret broker/dependency bundles, public-key signing и UI для полного
module lifecycle в Saga Console.
