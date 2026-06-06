# ADR 0003: Human-Gated AI Module Publication

- Status: Accepted
- Date: 2026-06-06

## Context

AI can accelerate module design, implementation, testing, and repair. It
cannot reliably determine by itself whether generated code is safe, correctly
scoped, economically acceptable, or appropriate to publish.

Direct AI writes to the active runtime would undermine the platform's contract
and safety model.

## Decision

- AI may create and repair draft module versions.
- AI cannot approve or publish its own module.
- Publication requires contract validation, tests, sandbox evidence, policy
  checks, and explicit human approval.
- Every lifecycle transition records actor, reason, version, and evidence.
- Generated artifacts retain provenance.

## Consequences

- The platform remains useful without claiming unsafe autonomy.
- Saga Console must provide a clear review and approval workflow.
- Validation and sandbox reports become product artifacts, not only logs.
- Approval APIs require strong authorization and audit events.

## Verification

No lifecycle implementation is complete until tests prove that an AI actor
cannot transition a module from draft to published.

