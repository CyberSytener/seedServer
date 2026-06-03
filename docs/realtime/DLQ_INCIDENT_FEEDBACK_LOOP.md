# DLQ Incident Feedback Loop (Phase 3)

## Purpose
Operationalize a closed loop for DLQ incidents:
1) detect,
2) triage,
3) tune thresholds/policies,
4) verify impact,
5) retain evidence.

This document is the policy layer for Phase 3 in `TASKS.md`.

## Trigger Conditions
Start this loop when any of the following alert classes fires:
- `DLQMaintenanceStalled`
- `DLQEligibleBacklogHigh`
- `DLQAutoTriageLagging`
- `DLQMaintenanceErrors`

## Loop Steps

### 1. Incident Snapshot (T0)
Capture the incident state using template:
- `docs/realtime/evidence/dlq_incident_feedback_TEMPLATE.md`

Required fields:
- alert name + firing interval,
- impacted environment,
- dominant DLQ message types,
- baseline values for `eligible/triaged/purged/alerts`.

### 2. Controlled Change
Apply one explicit change set at a time:
- threshold tuning (`SAGA_DLQ_MAINTENANCE_*`), or
- triage criteria changes, or
- purge cadence change.

Rules:
- no multi-axis changes in one iteration;
- document rollback condition before applying.

### 3. Verification Window (T0 + 24-72h)
Collect post-change metrics and compare to baseline:
- `seed_dlq_maintenance_eligible`
- `seed_dlq_maintenance_triaged_total`
- `seed_dlq_maintenance_purged_total`
- `seed_dlq_maintenance_alerts_total`

Decision:
- keep change,
- adjust and repeat,
- rollback.

### 4. Weekly Consolidation
At weekly DLQ review:
- include this incident in weekly evidence,
- record resulting threshold matrix delta,
- create follow-up root-cause item if recurring.

Template:
- `docs/realtime/evidence/dlq_weekly_review_TEMPLATE.md`

## Exit Criteria for One Feedback Cycle
A cycle is complete when all are true:
- incident snapshot created,
- controlled change applied with timestamp,
- verification snapshot captured after 24-72h,
- outcome decision recorded (keep/adjust/rollback).

## Ownership
- Primary: Reliability/Saga Ops owner on-call.
- Secondary: Platform owner for threshold policy approval in production.
