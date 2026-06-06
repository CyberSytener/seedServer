# Phase 0: Platform Foundation Stabilization

Status: Complete
Started: 2026-06-06

## Objective

Create a predictable canonical development baseline without deleting the
historical work that may still contain useful experiments.

This phase does not attempt to make every subsystem production-ready. It makes
the supported platform boundary explicit and prepares the repository for Module
Contract v1.

## Completed In This Pass

- Established GitHub `main` as the canonical source.
- Created a clean local development clone from canonical `main`.
- Preserved the previous dirty worktree as a recovery source.
- Declared active, candidate, experimental, and legacy scope levels.
- Documented the multi-phase product roadmap.
- Added ADRs for canonical scope, contract-first extension, and human-gated AI
  publication.
- Added one executable quality-gate entrypoint for portfolio, integration, and
  experimental checks.
- Added active-document link validation to the mandatory portfolio gate.
- Updated mandatory CI workflows to call the documented quality gates.

## Remaining Before Phase 1

- Run the portfolio demo smoke test from the canonical clean clone.
- Confirm all mandatory GitHub Actions stay green after the stabilization
  commit.
- Inventory useful unmerged changes in the recovery worktree.
- Import only changes that support the active platform direction.
- Open explicit cleanup tasks for active-surface legacy syntax and dependency
  debt.

## Recovery Worktree Policy

The previous worktree must not be force-reset or used for new commits. It may
contain valuable code that was not included in the portfolio publication.

To recover a change:

1. identify one coherent capability or fix;
2. compare it with canonical `main`;
3. copy or reimplement only the required files in a focused branch;
4. add focused tests;
5. pass the portfolio quality gate;
6. record promotion of a new active surface when applicable.

Do not bulk-copy the recovery worktree into canonical `main`.

## Phase 0 Exit Checklist

- [x] Canonical clean development clone exists.
- [x] Active platform scope is documented.
- [x] Product roadmap is documented.
- [x] Architectural decisions are recorded.
- [x] Portfolio and experimental quality tiers are separated.
- [x] CI calls the shared quality-gate entrypoint.
- [x] Portfolio quality gate passes from the clean clone.
- [x] Integration quality gate passes locally and is wired into CI.
- [x] Demo smoke passes from the clean clone.
- [x] Mandatory GitHub Actions are green.

## Next Phase

After the checklist is complete, Phase 1 begins with:

1. defining the Module Contract v1 schema;
2. implementing typed validation models;
3. migrating `modules/general_assistant.yaml`;
4. adding negative contract tests;
5. implementing input/output compatibility checks.
