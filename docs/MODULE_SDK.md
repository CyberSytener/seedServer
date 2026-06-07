# Module SDK And CLI

Last updated: 2026-06-07

The Phase 2 SDK gives humans and AI builders one repeatable local workflow for
creating, validating, testing, and subprocess-sandboxing a module package.

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
  remain unavailable even when listed.

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

## Current Safety Boundary

SDK tests load and execute local Python code in the developer process. They are
for trusted local development and are not sandbox evidence.

The subprocess sandbox is a stronger local evidence tier, but it does not yet
enforce network or full filesystem isolation and is not production-grade
untrusted-code containment. Reports expose these limits instead of hiding them.

An `sdk_module` remains visible to the registry and Saga Console for inspection,
but is intentionally not directly runnable through `/v1/modes` or executable in
a flow. A later runtime adapter must add hardened containment before generated
handlers can enter runtime flows.
