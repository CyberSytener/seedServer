# Audit Documentation Source of Truth

Updated: 2026-02-17

## Canonical audit artifacts (current)

Use these files as the primary source for current backend audit status and implementation priorities:

- `AUDIT_REPORT.md`
- `TASKS.md`
- `docs/jobs_api_contract.md`

## Historical artifacts (reference only)

The following directories contain historical snapshots and should be treated as archival context, not authoritative current-state contracts:

- `docs/audit/*.md` (older snapshots)
- `archive/reports/*`

## Rule

If historical docs conflict with current behavior, prefer:

1. Runtime code in `app/`
2. `AUDIT_REPORT.md`
3. `TASKS.md`
4. Legacy audit documents (context only)
