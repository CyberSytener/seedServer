# Source Of Truth

Last updated: 2026-06-06

## Canonical Source

- Canonical repository: `https://github.com/CyberSytener/seedServer`.
- Canonical branch: `main`.
- New development must start from a clean clone of canonical `main`.
- Dirty historical worktrees are recovery sources, not commit sources.
- Generated artifacts, local databases, secrets, and archive bundles do not
  belong in the canonical repository.

## Current Documentation Entrypoints

- Project setup and quick status: `README.md`.
- Product direction and phases: `docs/PLATFORM_ROADMAP.md`.
- Maintained platform boundary: `docs/ACTIVE_PLATFORM_SCOPE.md`.
- Test and CI commitments: `docs/TEST_STRATEGY.md`.
- Architectural decisions: `docs/adr/`.
- Reviewer setup and demo: `README.md` and `DEMO.md`.
- Historical plans and dated audits remain useful context, but they are not
  current sources of truth.

## Active-Scope Rules

- Do not keep archive folders, copy roots, or zip bundles inside the repository.
- Move snapshots, exported bundles and old copies to `../_archive/`.
- Keep generated runtime artifacts out of commits unless they are intentionally versioned fixtures.
- Before starting a feature, make sure `git status --short` is empty or
  understandable and scoped.
- Changes to the active surface must pass the portfolio quality gate.
- Candidate and experimental surfaces become active only through an ADR and
  focused release-blocking tests.

## Branch And Worktree Policy

- `main` must remain demoable and pass mandatory CI.
- Use focused branches and commits for architecture, cleanup, and product work.
- Never repair a massively dirty historical worktree by force-resetting it.
  Preserve it and import valuable changes intentionally into a clean clone.

## Verification Commands

PowerShell:

```powershell
Get-ChildItem -Force -Directory | Where-Object { $_.Name -match '(?i)(archive|copy|backup)' }
powershell -ExecutionPolicy Bypass -File scripts\audit_worktree.ps1
powershell -ExecutionPolicy Bypass -File scripts\audit_deleted_references.ps1
git status --short
git worktree list
```

Mandatory active-platform gate:

```powershell
python scripts/run_quality_gate.py portfolio
python scripts/run_quality_gate.py integration
python scripts/run_portfolio_demo.py --smoke-test --no-open
```

Frontend:

```powershell
Set-Location .\saga-console
npm run build
```

Broad historical unit checks remain available through:

```powershell
python scripts/run_quality_gate.py experimental
```
