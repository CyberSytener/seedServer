# DLQ Baseline — 2026-02-19

Status: Draft (to be filled from live telemetry)
Owner: Reliability / Saga Ops
Reviewer: Platform

## Window
- Baseline range: 2026-02-12 .. 2026-02-19 (7 days)
- Environments: staging, production

## Data Sources
- Prometheus metrics:
  - `seed_dlq_maintenance_eligible`
  - `seed_dlq_maintenance_triaged_total`
  - `seed_dlq_maintenance_purged_total`
  - `seed_dlq_maintenance_alerts_total`
- Logs:
  - `dlq_maintenance_cycle`
  - `dlq_maintenance_alert_threshold_exceeded`
- APIs:
  - `GET /api/v1/health/saga/dlq`
  - `GET /api/v1/health/saga/dlq/retry-candidates`

## Staging Baseline
- `eligible` p50/p95/max:
- `triaged_total` delta:
- `purged_total` delta:
- `alerts_total` delta (by reason):
- Dominant DLQ message types (top-3):
  1.
  2.
  3.

Assessment:
- Alert noise:
- Backlog trend:
- Triage lag risk:

## Production Baseline
- `eligible` p50/p95/max:
- `triaged_total` delta:
- `purged_total` delta:
- `alerts_total` delta (by reason):
- Dominant DLQ message types (top-3):
  1.
  2.
  3.

Assessment:
- Alert noise:
- Backlog trend:
- Triage lag risk:

## Proposed Threshold Deltas (Candidate)
(Use `docs/realtime/evidence/dlq_env_calibration_matrix_TEMPLATE.md` for final old→new matrix)

- staging:
  - `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD`: old -> new
  - `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS`: old -> new
  - `SAGA_DLQ_MAINTENANCE_LIST_LIMIT`: old -> new
  - `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD`: old -> new
  - `SAGA_DLQ_MAINTENANCE_PURGE_DAYS`: old -> new

- production:
  - `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD`: old -> new
  - `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS`: old -> new
  - `SAGA_DLQ_MAINTENANCE_LIST_LIMIT`: old -> new
  - `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD`: old -> new
  - `SAGA_DLQ_MAINTENANCE_PURGE_DAYS`: old -> new

## Decision
- [ ] Keep defaults
- [ ] Stage-only calibration
- [ ] Stage + Production promotion candidate

Notes:
