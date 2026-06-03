# DLQ Env Calibration Matrix — 2026-02-19

Status: Draft (pending live metrics fill)
Prepared by: Reliability / Saga Ops
Reviewed by: Platform

## Objective
Single old→new diff for `SAGA_DLQ_MAINTENANCE_*` across staging and production, based on baseline + verification window.

## Source Artifacts
- Baseline: `docs/realtime/evidence/dlq_baseline_2026-02-19.md`
- Verification window: `docs/realtime/evidence/dlq_verification_window_2026-02-19.md`
- Incident feedback: `docs/realtime/evidence/dlq_incident_feedback_YYYY-MM-DD.md` (if incident-driven)

## Baseline Summary
- Alert noise trend:
- Eligible backlog trend:
- Triage lag trend:
- Purge effectiveness:

## Env Matrix (old → new)

| ENV | Variable | Old | New | Reason | Expected effect | Rollback trigger |
|---|---|---|---|---|---|---|
| staging | `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_LIST_LIMIT` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_PURGE_DAYS` |  |  |  |  |  |
| staging | `SAGA_DLQ_MAINTENANCE_RETRY_DELAY_SECONDS` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_LIST_LIMIT` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_PURGE_DAYS` |  |  |  |  |  |
| production | `SAGA_DLQ_MAINTENANCE_RETRY_DELAY_SECONDS` |  |  |  |  |  |

## Rollout Plan
1. Apply staging values only.
2. Run T+24h check in verification window file.
3. If stable, run T+72h check.
4. Evaluate Promotion Gate in `docs/realtime/DLQ_RUNBOOK.md`.
5. Promote to production or adjust/rollback.

## Gate Decision
- [ ] Promote to production
- [ ] Keep staging only and iterate
- [ ] Rollback

Decision notes:

## Approvals
- Reliability owner:
- Platform approver:
- Date:
