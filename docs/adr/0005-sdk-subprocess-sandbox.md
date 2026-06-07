# ADR 0005: SDK Subprocess Sandbox Evidence

- Status: Accepted
- Date: 2026-06-07

## Context

Local golden-case tests prove handler behavior but execute trusted code in the
developer process. Phase 2 needs a stronger evidence tier before SDK modules can
be considered for runtime integration.

A subprocess boundary is useful for deterministic portfolio and development
work, but it is not equivalent to a container, virtual machine, or hardened
production sandbox.

## Decision

- `seed module sandbox` copies an SDK package into a temporary workspace and
  launches it through `python -I` in a separate process.
- The subprocess receives a minimal environment and communicates through a
  versioned file protocol rather than stdout.
- The parent enforces the declared wall timeout. Unix workers additionally
  attempt CPU and heap-memory limits.
- Handler stdout and stderr are captured with bounded evidence size.
- Reports state which limits were enforced and explicitly report that network
  and filesystem isolation are not yet enforced.
- Sandbox execution does not make an SDK module directly runnable or
  flow-executable.

## Consequences

- A failed, timed-out, or noisy handler cannot crash or corrupt the CLI process.
- Sandbox reports are structured evidence suitable for the future lifecycle
  gate.
- This boundary must not be marketed as production-grade untrusted-code
  containment.
- A later runtime adapter must add stronger network, filesystem, process-tree,
  and platform-independent memory isolation.

## Verification

- Tests prove subprocess execution, environment sanitization, timeout
  enforcement, bounded output capture, and pipeline rejection.
- Reports expose platform-specific limit enforcement.
- Existing API and flow guards continue to reject `sdk_module` execution.
