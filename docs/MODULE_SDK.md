# Module SDK And CLI

Last updated: 2026-06-07

The Module SDK gives humans and AI builders one repeatable local workflow for
creating, validating, testing, subprocess-sandboxing, and qualifying a module
package.

## Install And Use

Install the repository in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Create and verify a draft module:

```bash
seed module create text_normalizer
seed module validate text_normalizer
seed module test text_normalizer
seed module sandbox text_normalizer --input-file sample-input.json
seed module qualify text_normalizer
seed module status text_normalizer
seed module publish text_normalizer --actor reviewer --reason "approved release"
seed module deprecate text_normalizer --actor reviewer --reason "replaced" --replacement-version 0.2.0
seed module history text_normalizer
```

Pass `--json` to any command for a machine-readable report suitable for an AI
repair loop.

## Generated Package

```text
modules/text_normalizer/
  module.yaml
  handler.py
  README.md
```

The manifest uses `pipeline: sdk_module` with
`execution.adapter: module_sdk`. The generated handler imports only the stable
`app.module_sdk` interface and returns a dictionary that must satisfy the
declared output schema.

## Stable SDK Surface

- `ModuleExecutionContext`: module ID, run ID, execution mode, granted
  capabilities, and metadata.
- `ModuleHandler`: asynchronous handler protocol.
- `ModuleResult`: standard success/failure envelope.
- `ModuleSDKError`: declared handler failure with code, retryability, and
  details.
- `execute_module()`: input validation, handler execution, exception wrapping,
  and output validation.

## Validation And Test Reports

Package validation combines:

- Module Contract v1 diagnostics;
- required SDK package files;
- handler syntax;
- static Python import allowlist from `dependencies.python`; platform internals
  and internal `app.module_sdk.*` implementation modules remain unavailable
  even when listed.

`seed module test` executes manifest `tests.golden` cases and verifies both the
output schema and `expect_fields`. Reports contain stable diagnostic codes,
paths, messages, and per-case result envelopes.

## Subprocess Sandbox

`seed module sandbox`:

- validates the package before execution;
- copies it into a temporary workspace;
- launches `python -I` with a minimal environment;
- applies the declared wall timeout;
- attempts CPU and heap-memory limits on Unix;
- captures bounded stdout/stderr and returns structured evidence.

Use `--input '{"request":"hello"}'` where shell quoting is convenient, or
`--input-file sample-input.json` for a cross-platform input path. Without
either option, the first declared golden input is used. `--timeout-seconds`
may reduce, but never increase, the manifest timeout.

## Docker Hardened Sandbox

Build the minimal SDK runtime image once:

```bash
docker build -f Dockerfile.module-sandbox -t seed-module-sandbox:local .
```

Then run or qualify a package through the hardened adapter:

```bash
seed module sandbox text_normalizer --runtime docker
seed module qualify text_normalizer --runtime docker
```

The image can be selected with `--image` or
`SEED_MODULE_SANDBOX_IMAGE`. The adapter invokes Docker with no network,
a read-only root filesystem and package mount, dropped capabilities,
no-new-privileges, a non-root user, bounded memory/CPU/process counts, and a
small writable I/O mount used by the versioned worker protocol. The evidence
records the requested image, Docker engine version, declared capability policy,
and which hardening controls were actually applied.

Docker is optional for normal local development. If the CLI or engine is
unavailable, the command returns `sandbox.docker_unavailable`; it never falls
back to subprocess execution while claiming hardened evidence.

## Operation-Level Capability Enforcement

The one-shot sandbox worker installs a Python audit hook and activates it while
loading the handler and executing it through the stable SDK wrapper. The
observer records allowed operations and blocks undeclared:

- network access;
- filesystem reads and writes;
- child-process creation and execution.

`effects.filesystem_access: none` blocks reads and writes, `read_only` permits
reads, and `sandbox` permits reads and writes inside the runtime containment
boundary. Network operations require a declared non-`none` network policy.
Process access is always blocked because Module Contract v1 has no process
capability declaration.

The sandbox evidence includes the effective policy, bounded operation records,
violation count, and `python_audit_hook` enforcement marker. Capability
violations become structured `sandbox.capability_violation` failures. The
publish gate requires this report and rejects any report containing violations.

The observer covers handler import and execution. Import-loader code and
bytecode reads are explicitly allowed so declared dependencies can load, while
arbitrary file reads and all other import-time side effects remain blocked.
Worker startup, protocol I/O, and event-loop setup happen outside the observed
window. Environment reads are not covered by Python audit events; the sandbox
continues to rely on its sanitized environment and secret policy declarations.

## Secret And Dependency Publication Policy

The trusted sandbox adapter adds two reports after the worker finishes:

- `secret_report`: declared secret references, proof that no secret references
  were forwarded, broker availability, and policy status;
- `dependency_report`: declared Python dependencies, the static import
  allowlist enforcement mode, installed bundle, installer status, and policy
  status.

The current sandbox deliberately provides no secret broker and does not install
module-specific dependency bundles. A module may declare these requirements,
validate, test, and produce sandbox evidence, but the publish gate blocks it
with `sandbox.secret_broker_required` or
`sandbox.dependency_bundle_required`. This is fail-closed behavior: a
declaration is not treated as proof that the requirement was safely fulfilled.

Modules without secret references or external Python dependencies receive
positive policy evidence. Publication additionally rejects missing or
contract-mismatched policy reports. Future secret broker and dependency builder
adapters must replace these blockers with signed, verifiable fulfillment
evidence.

## Qualification And Evidence

`seed module qualify` runs validation, golden tests, and the selected sandbox
runtime, then writes append-only JSON evidence under
`.seed_artifacts/module_evidence/`.
Each record contains:

- the module ID and semantic version;
- a package fingerprint;
- a timestamp, evidence ID, kind, report hash, and full envelope integrity hash;
- the complete structured report.

The fingerprint covers package content but intentionally excludes the
`lifecycle` field. A code, contract, version, test, or documentation change
makes earlier evidence stale; a reviewed lifecycle transition does not.

`seed module status` only accepts passing evidence for the current fingerprint.
It reports stale and invalid records separately and explains whether the module
is technically ready for human approval or blocked from publication.

## Guarded Lifecycle

Use one explicit transition at a time:

```bash
seed module transition text_normalizer validated --actor reviewer --reason "contract passed"
seed module transition text_normalizer tested --actor reviewer --reason "golden cases passed"
seed module transition text_normalizer sandboxed --actor reviewer --reason "sandbox passed"
seed module transition text_normalizer approved --actor reviewer --reason "review complete"
```

Transitions require actor and reason, enforce
`draft -> validated -> tested -> sandboxed -> approved`, and write evidence for
both accepted and rejected attempts. The generic transition command cannot set
`published`; publication remains reserved for the dedicated publish gate.
`seed module status` also reconstructs the successful transition chain from
`draft`, so manually editing the YAML lifecycle cannot impersonate approval.
After changing an advanced module, use an explicit actor/reason transition back
to `draft`, then qualify the new fingerprint again.

## Signed Publish Gate

`seed module publish` is a separate gate, not a lifecycle alias. It:

- requires an evidence-backed `approved` lifecycle;
- requires passing evidence for the current package fingerprint;
- requires the latest sandbox report to assert enforced network and filesystem
  isolation;
- requires a clean operation-level capability report from the Python audit
  observer;
- requires matching secret and dependency policy reports with no unresolved
  broker or bundle requirements;
- requires that sandbox report to carry a valid HMAC-SHA256 authority
  signature;
- requires the approval transition to reference the exact evidence envelope
  hashes currently being published;
- records an `allow` or `block` decision with actor, reason, and exact evidence
  envelope hashes. A valid authority key signs the decision, and an unsigned
  decision can never allow publication.

If validation, test, or sandbox evidence changes after approval, the publish
gate blocks the module. Reset it to `draft`, advance it through the guarded
lifecycle again, and let the new approval bind the updated evidence.

The authority key is read from `SEED_MODULE_EVIDENCE_SIGNING_KEY` by default
and must contain at least 32 UTF-8 bytes. The key is never accepted as a CLI
argument and must never be committed. A different environment variable name
may be selected with `--signing-key-env`.
When `seed module qualify --runtime docker` is run with the authority key in
the host environment, the resulting evidence is signed after the container
finishes. The key is not passed into the container.
Inspecting an already published lifecycle also requires the same authority key
so `seed module status` can verify the signed publish decision.

The local subprocess sandbox deliberately reports network and filesystem
isolation as unenforced. Therefore normal local qualification reaches
`approved`, but `seed module publish` blocks it. Publication additionally
requires a signed Docker sandbox report with the complete hardening profile.

## Immutable Published Version History

A successful publish writes a signed, immutable package snapshot under
`.seed_artifacts/module_versions/`. The snapshot contains:

- the complete published package, including its published lifecycle manifest;
- the module ID, semantic version, and package fingerprint;
- actor, reason, exact qualification evidence hashes, approval reference, and
  publish-decision reference;
- a hash and size for every package file;
- a signed version-record envelope.

The publish gate refuses to reuse an already published `module_version` for a
different package fingerprint. A changed implementation or contract must
therefore advance its semantic version before publication. Existing snapshot
tampering also blocks reuse of that version slot.

`seed module history text_normalizer` verifies and lists published snapshots
without reading the current working module package. This keeps an old release
inspectable after the registry package changes or is removed. Pass
`--versions-root` to inspect a non-default store. When publish uses a custom
`--evidence-root` without an explicit versions root, it places version history
in the sibling `module_versions` directory.

## Signed Deprecation Gate

`seed module deprecate` is the only supported transition from `published` to
`deprecated`. The generic lifecycle transition command rejects direct
deprecation attempts.

The deprecation gate requires:

- an evidence-backed published lifecycle;
- the matching valid immutable version snapshot;
- the configured authority signing key;
- a non-empty actor and reason;
- an optional replacement that is a different valid semantic version.

An allowed decision updates the working manifest lifecycle and writes two
linked signed records: deprecation evidence in the evidence store and an
append-only deprecation record beside the immutable version snapshot. The
snapshot package itself remains unchanged with its original `published`
manifest. `seed module history` derives the release status from the linked
record and exposes its actor, reason, and recommended replacement.

Deprecation is irreversible in the current lifecycle. A replacement must be
published as a new semantic version instead of mutating or restoring the old
release.

## Current Safety Boundary

SDK tests load and execute local Python code in the developer process. They are
for trusted local development and are not sandbox evidence.

The subprocess sandbox is a stronger local evidence tier, but it does not
enforce network or full filesystem isolation. The Docker adapter adds a useful
container containment boundary, while the Python audit hook observes and blocks
supported Python-level network, filesystem, and process events. This is not a
VM, remote attestation service, kernel syscall tracer, or proof that native
extensions cannot perform unobserved operations. Reports expose these limits
instead of hiding them.

The local evidence store is append-only by command behavior and detects report
tampering through integrity hashes. Normal qualification and transition records
are unsigned by default, and the store is not protected from a user with
filesystem access. It is development and portfolio evidence, not a remote trust
authority.

Published version snapshots are immutable by command behavior and verify every
stored file and their envelope hash. Their HMAC signature is also verified when
the authority key is available. They are still a local filesystem registry,
not remote object-lock storage or a transparency log.

HMAC signatures establish that a record was produced by a holder of the shared
authority key. They do not provide public-key identity, key rotation,
transparency logging, or protection if that shared key is compromised.

An `sdk_module` remains visible to the registry and Saga Console for inspection,
but is intentionally not directly runnable through `/v1/modes` or executable in
a flow. A later flow-runtime integration must reuse a hardened execution
boundary before generated handlers can enter runtime flows.
