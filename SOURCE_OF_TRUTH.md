# Source Of Truth

Last updated: 2026-05-19

## Canonical Root

- Canonical server repository path: `seed_server/`.
- Archive and snapshot path: `../_archive/`.
- Active backend development should happen inside `seed_server/`.
- The separate NeoEats frontend snapshot currently lives at `../front-neoeats-snapshot/` and is not part of the `seed_server` git repository.

## Current Documentation Entrypoints

- Project setup and quick status: `README.md`.
- Current analysis and development plan: `docs/SYSTEM_ANALYSIS_AND_DEVELOPMENT_PLAN_2026-05-19.md`.
- Current state mark: `docs/STATE_MARK_2026-05-19.md`.
- Current project classification: `docs/PROJECT_CLASSIFICATION_2026-05-19.md`.
- Current cleanup inventory: `docs/CLEANUP_INVENTORY_2026-05-19.md`.
- Current import cleanup audit: `docs/VERIFY_IMPORTS_AUDIT_2026-05-20.md`.
- Current active review buckets: `docs/ACTIVE_REVIEW_BUCKETS_2026-05-20.md`.
- Current deleted-test coverage map: `docs/TEST_COVERAGE_CLEANUP_2026-05-20.md`.
- Public runtime runbook: `docs/PUBLIC_RUNTIME_RUNBOOK_2026-05-19.md`.
- Previous product outlook and next development plan: `docs/PROJECT_OUTLOOK_AND_NEXT_STEPS_2026-05-06.md`.
- Previous broad analysis and recommendations: `docs/CURRENT_PROJECT_ANALYSIS_2026-05-06.md`.
- NeoEats public routing and real-data readiness: `docs/NEOEATS_PUBLIC_AND_REAL_DATA_READINESS_2026-05-06.md`.
- Current backlog: `PROBLEMS_AND_TASKS.md`.
- Documentation index: `docs/guides/DOCUMENTATION_INDEX.md`.
- Historical phase tracker: `TASKS.md`.

## Active-Scope Rules

- Do not keep archive folders, copy roots or zip bundles inside `seed_server/`.
- Move snapshots, exported bundles and old copies to `../_archive/`.
- Keep generated runtime artifacts out of commits unless they are intentionally versioned fixtures.
- Before starting a feature, make sure `git status --short` is understandable and scoped.

## Branch And Worktree Policy

- `chore/archive-cleanup-canonical-root`: archive hygiene only.
- `refactor/code-fixes-baseline`: code fixes and refactoring only.
- `feature/phase0-followup`: current active feature/stabilization branch.

Keep archive cleanup, code fixes, documentation updates and product features in separate branches or separate commits.

## Verification Commands

PowerShell:

```powershell
Get-ChildItem -Force -Directory | Where-Object { $_.Name -match '(?i)(archive|copy|backup)' }
powershell -ExecutionPolicy Bypass -File scripts\audit_worktree.ps1
powershell -ExecutionPolicy Bypass -File scripts\audit_deleted_references.ps1
git status --short
git worktree list
```

Backend:

```powershell
python -m pytest -q tests/test_ci_smoke.py tests/test_auth_verify_user_context.py tests/unit/test_security_hardening.py tests/unit/test_llm_router_openai_regression.py
python -m pytest -q tests/unit --maxfail=1
python -m pytest -q tests/integration --maxfail=1
```

Frontend:

```powershell
Set-Location .\saga-console
npm run build
```

NeoEats frontend snapshot:

```powershell
Set-Location ..\front-neoeats-snapshot
npm run test:unit
npm run build
npm run smoke:server -- --port 5174
npm run smoke:flow
```

Public runtime check:

```powershell
Invoke-WebRequest -Uri https://neoeats.no/ -UseBasicParsing -TimeoutSec 10
Invoke-WebRequest -Uri https://api.neoeats.no/health -UseBasicParsing -TimeoutSec 10
docker compose -p seed_public -f docker-compose.public.yml --env-file .env.public ps
.\scripts\restore_public_runtime.ps1 -SkipDocker -SkipTunnel -SkipSmoke
.\scripts\smoke_public_neoeats.ps1
```
