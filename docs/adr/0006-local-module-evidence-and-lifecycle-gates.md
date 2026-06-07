# ADR 0006: Local Module Evidence And Lifecycle Gates

- Status: Accepted
- Date: 2026-06-07

## Context

Validation, tests, and subprocess sandbox runs return structured reports, but a
report printed to the terminal cannot support an auditable module lifecycle.
The platform needs to distinguish current evidence from evidence produced
before a package changed, while preserving human control over approval and
publication.

## Decision

- `seed module qualify` records validation, test, and sandbox reports in an
  append-only local evidence store.
- Every record contains a package fingerprint, report and envelope integrity
  hashes, evidence ID, timestamp, module version, and evidence kind.
- The fingerprint includes package content but excludes the mutable
  `lifecycle` field, so review transitions do not invalidate technical proof.
- `seed module status` accepts only passing evidence for the current
  fingerprint and reports stale or invalid records.
- `seed module transition` requires actor and reason, allows one declared stage
  at a time, and records accepted and rejected attempts.
- Status reconstructs the successful transition chain from `draft`; a lifecycle
  value without matching ordered evidence is rejected as unverified.
- An advanced module may explicitly reset to `draft` with actor and reason so a
  changed package can begin a new evidence cycle.
- The generic transition command cannot set `published`. Publication requires a
  future dedicated gate with hardened isolation evidence.

## Consequences

- Editing module code, contracts, tests, version, or documentation immediately
  makes previous qualification evidence stale.
- A module cannot skip validation, test, sandbox, or approval stages through
  the CLI.
- Local evidence is inspectable and tamper-detecting, but it is not signed and
  cannot resist a user with filesystem access.
- The platform now has a concrete boundary for a future signed evidence store
  and publish API.

## Verification

- Tests cover fingerprint stability, content invalidation, qualification,
  stale evidence, report tampering, ordered transitions, rejected stage skips,
  and direct-publish rejection.
- The portfolio quality gate includes the SDK and CLI lifecycle tests.
