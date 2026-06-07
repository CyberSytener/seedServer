# ADR 0010: Fail-Closed Secret And Dependency Policy

- Status: Accepted
- Date: 2026-06-07

## Context

Module Contract v1 lets a module declare secret references and external Python
dependencies. Static declarations and import checks do not prove that secrets
were safely delivered or that dependencies were reproducibly built and
verified. Treating those declarations as fulfilled would create a misleading
publication path.

## Decision

- Trusted subprocess and Docker adapters emit a `secret_report` and
  `dependency_report` outside the module worker.
- The current adapters forward no secret references and install no
  module-specific dependency bundle.
- Modules may declare secrets and dependencies for validation, testing, repair,
  and review, but publication blocks them until fulfillment evidence exists.
- Publication requires policy reports that match the current contract.
- Handler validation permits the public `app.module_sdk` interface but rejects
  imports of internal SDK implementation submodules.
- Secret references must be unique, matching the existing uniqueness rule for
  Python dependencies and capabilities.

## Consequences

- Simple self-contained SDK modules remain publishable through the hardened
  path.
- Modules needing secrets or external packages remain inspectable and
  repairable without receiving unsafe implicit access.
- A future secret broker and dependency builder have explicit evidence
  contracts to replace rather than hidden runtime assumptions.
- This decision does not observe environment reads or verify installed package
  provenance; it prevents those unsupported requirements from being published.

## Verification

- Contract tests reject duplicate secret references.
- Sandbox tests verify positive reports for self-contained modules and
  unresolved reports for declared requirements.
- Publish-gate tests reject secret-dependent and external-dependency modules.
- Docker CI verifies that a generated self-contained module produces passing
  secret and dependency policy reports.
