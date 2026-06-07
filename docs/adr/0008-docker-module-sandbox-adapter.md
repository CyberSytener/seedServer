# ADR 0008: Docker Module Sandbox Adapter

- Status: Accepted
- Date: 2026-06-07

## Context

The subprocess sandbox provides deterministic development evidence but cannot
enforce network or host-filesystem containment. The signed publish gate needs a
real adapter that can satisfy a documented hardening profile without making
Docker mandatory for normal portfolio review.

## Decision

- `seed module sandbox` and `seed module qualify` accept
  `--runtime subprocess|docker`; subprocess remains the default.
- The Docker adapter uses the minimal image built from
  `Dockerfile.module-sandbox`.
- Docker execution uses no network, a read-only root filesystem and package
  mount, dropped capabilities, no-new-privileges, a numeric non-root user,
  memory/CPU/PID limits, and a bounded writable protocol mount.
- The adapter records the image, engine version, declared policy, and applied
  hardening controls in sandbox evidence.
- Docker failures return structured diagnostics and never fall back to a less
  isolated runtime.
- Qualification signs evidence on the host after execution. The authority key
  is never passed into the sandbox container.
- Publication requires signed Docker evidence with the complete hardening
  profile.

## Consequences

- A reviewer can demonstrate a real container boundary when Docker is
  available while the default demo remains dependency-light.
- The Docker daemon and selected image are trusted infrastructure.
- The writable protocol mount is visible to module code, so the adapter proves
  containment rather than operation-level filesystem non-use.
- This is not VM isolation, remote attestation, public-key identity, or a
  complete dependency/secret policy.

## Verification

- Tests inspect the exact Docker command policy without requiring a daemon.
- Tests cover engine-unavailable diagnostics, signed Docker qualification,
  hardened publish requirements, and the unchanged subprocess default.
- CI builds the minimal image and runs a generated SDK module through the real
  Docker adapter on a Linux runner.
