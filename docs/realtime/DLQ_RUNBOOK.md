# DLQ Runbook (Persistent Saga DLQ)

## Цель

Операционный сценарий для triage/retry/purge сообщений в персистентном DLQ через health API.

## Предусловия

- Сервер запущен.
- Есть админ-доступ (`X-Admin-Key`).
- Включён Saga health router.

## Быстрый старт (CLI)

Используйте скрипт `scripts/dlq_runbook.py`.

### 1) Посмотреть кандидатов на retry

```bash
python scripts/dlq_runbook.py --admin-key <ADMIN_KEY> retry-candidates --limit 100
```

### 2) Запустить auto-triage в dry-run

```bash
python scripts/dlq_runbook.py --admin-key <ADMIN_KEY> auto-triage --types timeout_no_response adapter_circuit_open unknown_error
```

### 3) Применить auto-triage (с постановкой в retry)

```bash
python scripts/dlq_runbook.py --admin-key <ADMIN_KEY> auto-triage --apply --retry-delay-seconds 300 --retry-count-threshold 2 --min-age-minutes 10
```

### 4) Purge старых записей

```bash
python scripts/dlq_runbook.py --admin-key <ADMIN_KEY> purge --older-than-days 30 --limit 1000
```

## API операции

- `GET /api/v1/health/saga/dlq`
- `GET /api/v1/health/saga/dlq/retry-candidates`
- `POST /api/v1/health/saga/dlq/{saga_id}/retry`
- `POST /api/v1/health/saga/dlq/triage`
- `POST /api/v1/health/saga/dlq/purge`
- `POST /api/v1/health/saga/dlq/auto-triage`

Все операции защищены admin RBAC и пишут operator audit logs.

## Рекомендованная периодичность

- `retry-candidates`: каждые 5-10 минут.
- `auto-triage` dry-run: каждые 10-15 минут.
- `auto-triage --apply`: каждые 15-30 минут (по нагрузке).
- `purge`: ежедневно/еженедельно (в зависимости от retention политики).

## Встроенный scheduler (background worker)

DLQ maintenance теперь может выполняться автоматически в процессе API-сервиса.

Ключевые ENV:

- `SAGA_DLQ_MAINTENANCE_ENABLED` (default: `true`)
- `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS` (default: `900`)
- `SAGA_DLQ_MAINTENANCE_LIST_LIMIT` (default: `200`)
- `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD` (default: `2`)
- `SAGA_DLQ_MAINTENANCE_MIN_AGE_MINUTES` (default: `10`)
- `SAGA_DLQ_MAINTENANCE_TYPES` (csv, optional)
- `SAGA_DLQ_MAINTENANCE_TRIAGE_STATUS` (default: `queued_for_retry`)
- `SAGA_DLQ_MAINTENANCE_TRIAGE_NOTE` (default: `scheduled auto-triage`)
- `SAGA_DLQ_MAINTENANCE_RETRY_DELAY_SECONDS` (default: `300`)
- `SAGA_DLQ_MAINTENANCE_PURGE_ENABLED` (default: `true`)
- `SAGA_DLQ_MAINTENANCE_PURGE_DAYS` (default: `30`)
- `SAGA_DLQ_MAINTENANCE_PURGE_LIMIT` (default: `1000`)
- `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD` (default: `50`)

Логи цикла:

- `dlq_maintenance_cycle` — итог triage/purge за цикл
- `dlq_maintenance_alert_threshold_exceeded` — сигнал при превышении порога eligible DLQ

Метрики цикла (Prometheus):

- `seed_dlq_maintenance_cycles_total{status="success|error"}`
- `seed_dlq_maintenance_eligible`
- `seed_dlq_maintenance_triaged_total`
- `seed_dlq_maintenance_purged_total`
- `seed_dlq_maintenance_alerts_total{reason="eligible_threshold_exceeded"}`

Alert rules (Prometheus):

- `DLQMaintenanceStalled`
- `DLQEligibleBacklogHigh`
- `DLQAutoTriageLagging`
- `DLQMaintenanceErrors`

Источник правил: `archive/monitoring/alert_rules.yml`

## SLO-тюнинг по окружениям

Рекомендуемый baseline (стартовые значения, потом корректировать по фактической нагрузке):

| Окружение | Alert threshold | Purge days | Retry threshold | Maintenance interval |
|---|---:|---:|---:|---:|
| dev | 100 | 7 | 1 | 300s |
| staging | 75 | 14 | 2 | 600s |
| production | 50 | 30 | 2 | 900s |

Минимальный ENV profile для prod:

```bash
SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD=50
SAGA_DLQ_MAINTENANCE_PURGE_DAYS=30
SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD=2
SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS=900
```

Шаблон env-калибровки (единый old→new diff):

- `docs/realtime/evidence/dlq_env_calibration_matrix_TEMPLATE.md`

## Promotion gate (staging -> production)

Перед переносом новых порогов из staging в production должны быть выполнены все пункты:

1. **Baseline зафиксирован**
	- есть файл `dlq_baseline_*.md` за 7 дней;
	- заполнена env-матрица `dlq_env_calibration_matrix_*.md` с old→new diff.

2. **Staging verification completed (>=24h)**
	- нет роста `seed_dlq_maintenance_eligible` относительно baseline p95;
	- `seed_dlq_maintenance_alerts_total` не показывает усиление шумовых алертов;
	- triage/purge цикл стабилен (без `DLQMaintenanceErrors`).

3. **Feedback loop evidence complete**
	- заполнен `dlq_incident_feedback_*.md` (или отмечено, что инцидента не было в окне);
	- weekly review отражает решение по порогам.

4. **Rollback path defined**
	- для каждого изменённого `SAGA_DLQ_MAINTENANCE_*` указан rollback trigger;
	- rollback значения зафиксированы в env-матрице.

Если любой пункт не выполнен — promotion блокируется, проводится дополнительная калибровка в staging.

## Инцидентные playbooks

## Phase 3 execution links

- Phase checklist: `docs/realtime/DLQ_LIVE_PHASE3_CHECKLIST.md`
- Feedback loop policy: `docs/realtime/DLQ_INCIDENT_FEEDBACK_LOOP.md`
- Evidence templates: `docs/realtime/evidence/README.md`

### `DLQMaintenanceStalled`

1. Проверить, жив ли background worker (`SAGA_DLQ_MAINTENANCE_ENABLED=true`, логи `dlq_maintenance_cycle`).
2. Если worker не запускается — перезапустить API pod/service и проверить startup logs.
3. Выполнить ручной dry-run triage через `scripts/dlq_runbook.py`.

### `DLQEligibleBacklogHigh`

1. Запустить `retry-candidates` и определить dominant failure types.
2. Выполнить `auto-triage --apply` с `--min-age-minutes` и `--retry-count-threshold` для контроля риска повторных фейлов.
3. Зафиксировать top error types в инциденте и создать follow-up на root cause.

### `DLQAutoTriageLagging`

1. Проверить параметры scheduler (`interval`, `list_limit`, `retry_threshold`).
2. Увеличить `SAGA_DLQ_MAINTENANCE_LIST_LIMIT` или уменьшить `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS`.
3. Повторно проверить тренд `seed_dlq_maintenance_eligible` за 30-60 минут.

### `DLQMaintenanceErrors`

1. Проверить ошибки в логах maintenance цикла.
2. Временно отключить purge (`SAGA_DLQ_MAINTENANCE_PURGE_ENABLED=false`), если ошибка связана с purge SQL/path.
3. Запустить ручные операции triage/purge для верификации после фикса.

## Evidence discipline (required for live calibration)

- Baseline collection: `docs/realtime/evidence/dlq_baseline_TEMPLATE.md`
- Incident feedback cycle: `docs/realtime/evidence/dlq_incident_feedback_TEMPLATE.md`
- Weekly review cadence: `docs/realtime/evidence/dlq_weekly_review_TEMPLATE.md`
- Env old→new calibration matrix: `docs/realtime/evidence/dlq_env_calibration_matrix_TEMPLATE.md`
