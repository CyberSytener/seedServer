# ADR 0001: Canonical Source And Active Scope

- Status: Accepted
- Date: 2026-06-06

## Context

The project evolved through many experiments, reports, generated artifacts,
and partially replaced implementations. The previous local worktree contained
thousands of unrelated changes, while the public GitHub branch had become the
clean portfolio distribution.

Treating every historical file as equally active made CI noisy and made future
architectural work unsafe.

## Decision

- GitHub `main` is the canonical project source.
- New development starts from a clean clone of canonical `main`.
- The previous dirty worktree is preserved as a recovery source and is not
  used for new commits.
- Product surfaces are classified as active, candidate, experimental, or
  legacy in `docs/ACTIVE_PLATFORM_SCOPE.md`.
- Only declared active behavior is a mandatory portfolio release gate.

## Consequences

- Supported behavior becomes easier to understand and protect.
- Historical experiments remain available without pretending to be supported.
- Promotion of a new subsystem requires documentation and focused tests.
- Valuable changes found in the recovery worktree must be imported
  intentionally and reviewed.

## Verification

```bash
git status --short
python scripts/run_quality_gate.py portfolio
```

