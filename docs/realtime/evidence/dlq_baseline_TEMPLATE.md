# DLQ Baseline Template

Date range: YYYY-MM-DD .. YYYY-MM-DD
Environment: dev / staging / production
Owner:

## Metrics Snapshot (7-day)
- `seed_dlq_maintenance_eligible`
  - p50:
  - p95:
  - max:
- `seed_dlq_maintenance_triaged_total`
  - total delta:
- `seed_dlq_maintenance_purged_total`
  - total delta:
- `seed_dlq_maintenance_alerts_total`
  - total alerts:
  - by reason:

## Dominant DLQ Types
Top message types:
1.
2.
3.

## Baseline Assessment
- Current alert threshold fit:
- Evidence of noise (false positives):
- Evidence of lag/backlog:

## Proposed Calibration
- `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD`: old -> new
- `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS`: old -> new
- `SAGA_DLQ_MAINTENANCE_LIST_LIMIT`: old -> new
- `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD`: old -> new
- `SAGA_DLQ_MAINTENANCE_PURGE_DAYS`: old -> new

## Approval
- Reviewer:
- Decision: approve / adjust / reject
- Notes:
