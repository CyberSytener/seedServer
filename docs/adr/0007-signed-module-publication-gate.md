# ADR 0007: Signed Module Publication Gate

- Status: Accepted
- Date: 2026-06-07

## Context

Integrity hashes detect modifications to local evidence, but they do not
identify the authority that accepted a publication. The platform also needs a
dedicated publication operation that cannot be replaced by editing the
manifest lifecycle.

## Decision

- Evidence records may carry an HMAC-SHA256 signature from the configured
  module evidence authority.
- The shared authority key is read from an environment variable, must contain
  at least 32 UTF-8 bytes, and is never accepted as a CLI value.
- `seed module publish` requires an evidence-backed `approved` lifecycle,
  passing current-fingerprint evidence, a validly signed sandbox report, and
  enforced network and filesystem isolation.
- Every publish attempt records an `allow` or `block` decision with actor,
  reason, package fingerprint, and exact evidence envelope hashes.
- The successful approval transition must reference the same validation, test,
  and sandbox envelope hashes that are presented to the publish gate.
- Successful publish decisions are signed and become the only evidence that
  can advance lifecycle from `approved` to `published`.
- The existing local subprocess sandbox cannot satisfy the hardened isolation
  requirements and therefore cannot publish a module.

## Consequences

- A generated module cannot publish itself through lifecycle editing or normal
  local qualification.
- Reviewers can inspect why publication was blocked and which exact evidence
  justified an allowed decision.
- HMAC uses a shared secret. It does not provide asymmetric identity,
  transparency logging, remote durability, or safety after key compromise.
- A future hardened runtime adapter must hold or access the authority key and
  sign its sandbox attestation.

## Verification

- Tests cover matching and incorrect authority keys, unsigned local sandbox
  rejection, signed block decisions, successful signed hardened publication,
  stale post-approval evidence rejection, short-key rejection, CLI
  environment-key loading, and published lifecycle reconstruction.
