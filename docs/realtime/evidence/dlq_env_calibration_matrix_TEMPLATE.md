# DLQ Env Calibration Matrix Template

Calibration window: YYYY-MM-DD .. YYYY-MM-DD
Prepared by:
Reviewed by:

## Objective
Capture a single old→new diff for `SAGA_DLQ_MAINTENANCE_*` per environment based on live baseline.

## Baseline Summary
- Source artifact: `dlq_baseline_YYYY-MM-DD.md`
- Observed symptoms:
  - alert noise:
  - eligible backlog trend:
  - triage lag:

## Env Matrix (old → new)

| ENV | Variable | Old | New | Reason | Expected effect | Rollback trigger |
|---|---|---|---|---|---|---|
| staging | `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_LIST_LIMIT` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_PURGE_DAYS` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_LIST_LIMIT` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_PURGE_DAYS` |  |  |  |  |  |

## Rollout Plan
1. Apply to staging.
2. Observe for 24h (minimum).
3. Evaluate Promotion Gate.
4. Promote to production if gate passes.

## Verification Snapshot (post-change)
- `seed_dlq_maintenance_eligible` p95:
- `seed_dlq_maintenance_alerts_total` delta:
- `seed_dlq_maintenance_triaged_total` delta:
- `seed_dlq_maintenance_purged_total` delta:

Decision:
- [ ] Promote
- [ ] Adjust and re-run
- [ ] Rollback
