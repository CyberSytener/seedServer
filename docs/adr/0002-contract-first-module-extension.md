# ADR 0002: Contract-First Module Extension

- Status: Accepted
- Date: 2026-06-06

## Context

Seed Platform aims to let humans and AI extend the system with new modules.
Current YAML module definitions describe useful input/output and capability
information, but they do not fully describe execution behavior, side effects,
permissions, resource limits, or compatibility.

Allowing generated code to integrate through implementation details would
couple modules to platform core and make automated review unsafe.

## Decision

- New module capabilities are introduced through versioned declarative
  contracts.
- Contracts describe data, behavior, effects, permissions, resources, errors,
  compatibility, and evidence.
- Runtime integration depends on contract and SDK interfaces, not direct access
  to FastAPI application state or infrastructure internals.
- Contract validation happens before tests, sandboxing, approval, or
  publication.
- Module Contract v1 is the next platform implementation phase.

## Consequences

- AI receives a bounded language for proposing modules.
- Compatibility and policy checks can happen before execution.
- Existing modules require an explicit migration path.
- Contract evolution requires versioning and adapters.

## Verification

Phase 1 must provide:

- a Module Contract v1 schema;
- Python validation models;
- migration of `general_assistant.yaml`;
- negative contract tests;
- compatibility checks.

