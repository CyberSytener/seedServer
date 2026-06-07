# ADR 0009: Python Audit Capability Enforcement

- Status: Accepted
- Date: 2026-06-07

## Context

Container hardening can contain a module, but the publication gate also needs
structured evidence showing whether module behavior matched its declared
capabilities. Module Contract v1 already declares network and filesystem
effects, while process execution is intentionally unavailable.

## Decision

- The one-shot sandbox worker installs a Python audit hook.
- The hook covers handler import and stable SDK execution. Import-loader code
  and bytecode reads are explicitly allowed, while arbitrary reads and all
  other import-time side effects are blocked. Worker startup, protocol I/O, and
  event-loop setup remain outside the observed window.
- Undeclared Python-level network and filesystem operations are blocked.
- Child-process creation and execution are always blocked because Contract v1
  has no process-access declaration.
- The worker emits a bounded operation report with the effective policy,
  allowed and blocked operations, violation count, and truncation state.
- The publish gate requires a `python_audit_hook` report with zero violations.

## Consequences

- Capability mismatches become structured diagnostics suitable for human and
  AI repair loops.
- The subprocess adapter can demonstrate policy behavior, but only Docker
  evidence can satisfy the complete hardened publication profile.
- Audit hooks are process-global and cannot be removed, which is acceptable
  because every sandbox worker is a one-shot process.
- Python audit events do not provide kernel syscall tracing, native-extension
  visibility, environment-read observation, or remote attestation.

## Verification

- Unit tests cover allowed reads and blocked filesystem writes, network access,
  and child-process execution.
- Publish-gate tests reject missing observation evidence and non-zero
  capability violations.
- CI builds the sandbox image and confirms that a generated module produces a
  clean audit report through the real Docker adapter.
