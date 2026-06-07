# ADR 0004: Module SDK Local Execution Boundary

- Status: Accepted
- Date: 2026-06-07

## Context

Phase 2 needs a standard handler interface and repeatable tooling before AI can
propose executable modules. Loading generated Python directly into the active
runtime would bypass the contract-first and human-gated publication model.

## Decision

- SDK-authored modules declare `pipeline: sdk_module` and
  `execution.adapter: module_sdk`.
- The first SDK slice supports local create, validate, and golden-case test
  commands.
- Local SDK tests execute in the developer process and do not count as sandbox
  or publication evidence.
- `sdk_module` packages remain non-runnable through the API and non-executable
  in flows until an isolated runtime adapter is implemented.
- Handler imports are statically checked against the standard library,
  `app.module_sdk`, and the manifest `dependencies.python` allowlist. Other
  platform internals remain forbidden even when listed.

## Consequences

- Humans and AI use the same module package layout and diagnostics.
- The platform gains a useful generation loop without overstating runtime
  isolation.
- The next SDK slice has a clear responsibility: isolated execution and runtime
  adapter integration.

## Verification

- Generated packages pass Contract v1 validation.
- Golden cases pass through the standard input/output validation wrapper.
- Undeclared platform-internal imports fail package validation.
- API and flow guards continue to reject `sdk_module` execution.
