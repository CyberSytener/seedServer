# ADR 0014: Bounded Module Repair Loop

- Status: Accepted
- Date: 2026-06-07

## Context

Durable rejection records preserve the exact failed candidate and structured
diagnostics, but they do not define how an AI or human builder should consume
that information or how repaired candidates should be evaluated. Sending an
unbounded repository context to a model, accepting identity changes, or letting
generated code publish itself would weaken the platform's contract-first and
human-gated architecture.

## Decision

- `seed module repair-plan` builds a versioned context pack only from a signed
  durable rejection.
- The pack includes the full Module Contract schema, rejected text files,
  structured reports, previous attempt summaries, allowed paths, and explicit
  output constraints.
- Context size is bounded to 128 KiB by default and 256 KiB maximum.
- A rejection permits at most three recorded repair attempts.
- A successful attempt closes that rejection's repair loop.
- `seed module repair-check` requires a changed candidate with the same module
  ID and semantic version, runs the complete qualification path, and reports
  resolved, remaining, and introduced diagnostic codes.
- Each attempted candidate is stored as a complete signed snapshot with actor,
  generator, qualification report, and repair evidence reference.
- The repair loop does not call a model, apply file changes, or publish a
  candidate. Provider integration and artifact application remain separate
  future adapters.

## Consequences

- Humans and AI providers receive the same deterministic repair input.
- Failed attempts remain inspectable and cannot continue indefinitely.
- Candidate identity, provenance, and qualification evidence remain auditable.
- Repair success means qualification-ready, not approved or published.
- Large or non-UTF-8 candidates fail closed instead of silently truncating
  repair context.

## Verification

- SDK tests verify bounded self-contained context, successful repair,
  unsuccessful recorded attempts, unchanged-candidate blocking, and budget
  exhaustion.
- CLI tests cover plan generation and successful repair qualification.
- Rejection-history verification checks every stored repair file, fingerprint,
  identity, integrity hash, and authority signature.
