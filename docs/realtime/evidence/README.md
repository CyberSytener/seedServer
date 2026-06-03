# DLQ Evidence Templates

These templates support Phase 3 execution from `TASKS.md` and `DLQ_LIVE_PHASE3_CHECKLIST.md`.

## Templates
- `dlq_baseline_TEMPLATE.md` — 7-day per-environment baseline collection.
- `dlq_incident_feedback_TEMPLATE.md` — incident-to-threshold feedback loop record.
- `dlq_weekly_review_TEMPLATE.md` — weekly ops review snapshot and decision log.
- `dlq_env_calibration_matrix_TEMPLATE.md` — unified old→new env diff for `SAGA_DLQ_MAINTENANCE_*`.

## Usage
1. Copy the relevant template and rename with date/week.
2. Store under this folder (e.g. `dlq_baseline_2026-02-25.md`).
3. Link the file in incident ticket or weekly review note.

## Current working files
- `dlq_baseline_2026-02-19.md` — active baseline candidate for live calibration.
- `dlq_verification_window_2026-02-19.md` — T+24h / T+72h operational verification checklist.
- `dlq_env_calibration_matrix_2026-02-19.md` — active old→new env diff sheet for `SAGA_DLQ_MAINTENANCE_*`.
