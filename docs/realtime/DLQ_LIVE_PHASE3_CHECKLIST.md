# DLQ Live Phase 3 Checklist

Date: 2026-02-18
Owner: Reliability / Saga Ops

## Goal
Close the remaining deep-research recommendation for DLQ live operational readiness:
- environment-calibrated SLO thresholds from real traffic,
- post-incident feedback loop,
- repeatable operator evidence for weekly review.

## Scope and Inputs
- Existing runbook: `docs/realtime/DLQ_RUNBOOK.md`
- Existing maintenance controls: `SAGA_DLQ_MAINTENANCE_*` env vars
- Existing metrics:
  - `seed_dlq_maintenance_cycles_total`
  - `seed_dlq_maintenance_eligible`
  - `seed_dlq_maintenance_triaged_total`
  - `seed_dlq_maintenance_purged_total`
  - `seed_dlq_maintenance_alerts_total`

## Phase 3 Tasks

### 1) Baseline collection (staging/prod)
- [ ] Collect 7-day baseline for `eligible`, `triaged`, `purged`, `alerts`.
- [ ] Compute p50/p95 for `eligible` by environment.
- [ ] Capture incident count and top DLQ message types for the same window.

Evidence artifact:
- `docs/realtime/evidence/dlq_baseline_YYYY-MM-DD.md`

### 2) Threshold calibration
- [ ] Propose per-environment values for:
  - `SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD`
  - `SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS`
  - `SAGA_DLQ_MAINTENANCE_LIST_LIMIT`
  - `SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD`
  - `SAGA_DLQ_MAINTENANCE_PURGE_DAYS`
- [ ] Dry-run in staging for 24h.
- [ ] Promote to production after review.

Acceptance:
- alert noise reduced without increasing unresolved DLQ backlog.

### 3) Post-incident feedback loop
- [ ] Standardize incident template fields:
  - trigger metric/alert,
  - root cause category,
  - changed threshold/policy,
  - verification metric after change,
  - rollback condition.
- [ ] Require one follow-up verification snapshot 24-72h after each incident change.

Evidence artifact:
- `docs/realtime/evidence/dlq_incident_feedback_YYYY-MM-DD.md`

### 4) Weekly ops review rhythm
- [ ] Define weekly DLQ review checklist:
  - trend of `eligible` vs `triaged`,
  - repeated failure classes,
  - noisy alerts,
  - recommended threshold deltas.
- [ ] Keep change log of threshold updates and rationale.

Evidence artifact:
- `docs/realtime/evidence/dlq_weekly_review_YYYY-WW.md`

## Exit Criteria (Phase 3 Done)
- Two consecutive weekly reviews completed with evidence files.
- At least one incident feedback cycle completed end-to-end.
- Environment-specific threshold matrix finalized and referenced from `DLQ_RUNBOOK.md`.
- No unresolved action items from weekly review older than 14 days.

## Next
After Phase 3 closure, continue with advanced orchestration maturity (Phase 4 in `TASKS.md`).
