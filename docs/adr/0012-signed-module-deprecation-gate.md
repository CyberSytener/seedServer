# ADR 0012: Signed Module Deprecation Gate

- Status: Accepted
- Date: 2026-06-07

## Context

The generic lifecycle transition previously allowed `published -> deprecated`.
That transition recorded actor and reason, but it did not require authority
signing or prove which immutable published package was being withdrawn.
Registry consumers and AI builders need deprecation to be an auditable release
decision, not a mutable manifest edit.

## Decision

- `seed module deprecate` is the only supported deprecation path.
- The gate requires an evidence-backed published lifecycle, the matching
  immutable version snapshot, a valid authority signing key, actor, and reason.
- An optional replacement must be a different valid semantic version.
- An allowed decision writes signed evidence and a linked append-only
  deprecation record beside the immutable version snapshot.
- Version history verifies deprecation record integrity, signature when the
  authority key is available, module identity, and exact version reference.
- The immutable snapshot package remains unchanged. History derives its
  effective release lifecycle from linked deprecation records.
- Deprecation is irreversible in the current lifecycle.

## Consequences

- A manifest edit or generic transition cannot impersonate a valid
  deprecation.
- Reviewers can inspect who deprecated a version, why, and which replacement
  was recommended after the working package changes or disappears.
- A compromised shared HMAC key can still forge decisions. Public-key
  identities and key rotation remain future work.
- The local append-only store does not provide remote object lock or a
  transparency log.

## Verification

- SDK tests reject generic deprecation transitions and missing version
  snapshots.
- SDK tests verify signed deprecation, lifecycle reconstruction, and
  replacement metadata.
- SDK tests detect tampered deprecation records.
- CLI tests publish, deprecate, and inspect a version through history.
