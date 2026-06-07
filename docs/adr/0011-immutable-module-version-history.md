# ADR 0011: Immutable Module Version History

- Status: Accepted
- Date: 2026-06-07

## Context

The publication gate previously changed the working manifest to `published`
and recorded evidence, but it did not preserve the package that was actually
approved. Later edits could leave evidence for an old fingerprint without an
inspectable release artifact. Reusing one semantic version for different
package content would also make registry consumers and AI builders unable to
reason reliably about compatibility.

## Decision

- A successful publish writes a signed immutable package snapshot to
  `.seed_artifacts/module_versions/`.
- Every snapshot stores the complete published package, per-file hashes and
  sizes, its package fingerprint, actor and reason, exact qualification
  evidence references, approval reference, and publish-decision reference.
- History verification checks the record envelope, every declared file,
  undeclared files, published manifest lifecycle, and package fingerprint. It
  also verifies the HMAC signature when the authority key is available.
- Publication blocks a different fingerprint from reusing an existing
  `module_version`.
- `seed module history <module_id>` inspects history independently of the
  current working registry package.

## Consequences

- Published modules remain inspectable after their working package changes or
  disappears.
- Module authors must advance semantic versions for changed release content.
- Tampered snapshots become explicit invalid history and block ambiguous
  version reuse.
- The store remains local filesystem infrastructure. It does not provide
  remote object lock, public-key verification, key rotation, or transparency
  logging.

## Verification

- SDK tests prove history survives a working-package change.
- SDK tests reject semantic-version reuse by a different fingerprint.
- SDK tests detect modified snapshot files.
- CLI tests publish and inspect a version through `seed module history`.
