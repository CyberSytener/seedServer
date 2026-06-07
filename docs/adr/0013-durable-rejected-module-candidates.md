# ADR 0013: Durable Rejected Module Candidates

- Status: Accepted
- Date: 2026-06-07

## Context

Validation and publication blockers were recorded in fingerprint-bound
evidence, but the rejected package itself remained only in the working module
registry. Once a human or AI builder edited or removed that package, reviewers
could no longer inspect the exact failed candidate or use its diagnostics as a
stable repair-loop input.

Rejection is not a lifecycle state. A rejected candidate should remain
repairable and may later advance after receiving a new fingerprint and fresh
evidence.

## Decision

- `seed module reject` records a signed rejection decision for an unpublished
  candidate without changing its lifecycle.
- The gate requires an authority signing key, actor, and reason.
- Published and deprecated releases must use the deprecation gate instead.
- An allowed rejection writes a complete signed candidate snapshot under
  `.seed_artifacts/module_rejections/`.
- The snapshot includes per-file integrity data and structured repair context:
  diagnostics, warnings, publication blockers, recommended lifecycle, and
  current evidence references and full qualification reports.
- `seed module rejections <module_id>` verifies and lists history independently
  of the current working package.

## Consequences

- Rejected candidates remain inspectable after repair or removal.
- AI builders receive stable structured feedback and the exact failed input
  needed for a future repair loop.
- Multiple rejections of the same fingerprint are allowed because they may
  represent distinct reviewer decisions.
- Rejection does not mutate lifecycle or block subsequent qualification.
- The shared HMAC and local filesystem limitations documented for publication
  history also apply to rejection history.

## Verification

- SDK tests prove repair context and rejected code survive working-package
  changes.
- SDK tests block rejection of a published release and unsigned decisions.
- SDK tests detect tampered rejected candidate files.
- CLI tests reject and independently inspect a candidate.
