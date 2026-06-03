# DLQ Verification Window — 2026-02-19

Purpose: Operational checklist for post-change verification at T+24h and T+72h.
Scope: staging first, production only after Promotion Gate in `docs/realtime/DLQ_RUNBOOK.md`.

## Change Set
- Change ticket/PR:
- Applied by:
- Applied at (UTC):
- Environment:
- Variables changed (`SAGA_DLQ_MAINTENANCE_*`):

## Baseline Reference
- Baseline file: `docs/realtime/evidence/dlq_baseline_2026-02-19.md`
- Env matrix file: `docs/realtime/evidence/dlq_env_calibration_matrix_YYYY-MM-DD.md`

## T+24h Checkpoint
Timestamp (UTC):

Metrics vs baseline:
- `seed_dlq_maintenance_eligible` p95: baseline -> now
- `seed_dlq_maintenance_alerts_total` delta: baseline -> now
- `seed_dlq_maintenance_triaged_total` delta: baseline -> now
- `seed_dlq_maintenance_purged_total` delta: baseline -> now

Health checks:
- [ ] No sustained `DLQMaintenanceErrors`
- [ ] No `DLQMaintenanceStalled` incident after change
- [ ] Alert noise not increased
- [ ] Eligible backlog trend stable or improved

Decision at T+24h:
- [ ] Continue to T+72h
- [ ] Adjust thresholds and restart window
- [ ] Rollback

Notes:

## T+72h Checkpoint
Timestamp (UTC):

Metrics vs baseline:
- `seed_dlq_maintenance_eligible` p95: baseline -> now
- `seed_dlq_maintenance_alerts_total` delta: baseline -> now
- `seed_dlq_maintenance_triaged_total` delta: baseline -> now
- `seed_dlq_maintenance_purged_total` delta: baseline -> now

Health checks:
- [ ] No sustained `DLQMaintenanceErrors`
- [ ] No `DLQMaintenanceStalled` incident after change
- [ ] Alert noise acceptable
- [ ] Backlog/triage lag trend acceptable

Final decision:
- [ ] Promote (if staging)
- [ ] Keep as-is (if production)
- [ ] Adjust and rerun verification
- [ ] Rollback

## Promotion Gate Summary
- [ ] Baseline completed
- [ ] Env matrix old→new completed
- [ ] Incident feedback evidence attached (or N/A explicitly documented)
- [ ] Rollback triggers documented and tested

Approvals:
- Reliability owner:
- Platform approver:
- Date:
