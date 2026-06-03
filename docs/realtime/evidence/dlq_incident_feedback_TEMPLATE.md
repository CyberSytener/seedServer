# DLQ Incident Feedback Template

Incident ID:
Date/time (UTC):
Environment:
Owner:

## Trigger
- Alert name:
- Fire interval:
- Symptom summary:

## T0 Baseline
- `eligible`:
- `triaged_total`:
- `purged_total`:
- `alerts_total`:
- Dominant DLQ types:

## Root Cause Category
- [ ] traffic burst
- [ ] provider instability
- [ ] policy threshold too strict/lenient
- [ ] maintenance scheduler lag
- [ ] purge behavior
- [ ] other:

## Change Applied (Single Controlled Change)
- Parameter/policy changed:
- Old value:
- New value:
- Apply timestamp:
- Rollback condition:

## Verification (T0 + 24-72h)
- `eligible` trend:
- `triaged_total` delta:
- `purged_total` delta:
- `alerts_total` delta:
- Outcome vs baseline:

## Decision
- [ ] keep change
- [ ] adjust and rerun loop
- [ ] rollback

## Follow-ups
- Root-cause task:
- Owner:
- ETA:
