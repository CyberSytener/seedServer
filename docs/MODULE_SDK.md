# Module SDK And CLI

Last updated: 2026-06-07

The first Phase 2 SDK slice gives humans and AI builders one repeatable local
workflow for creating, validating, and testing a module package.

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

## Current Safety Boundary

SDK tests load and execute local Python code in the developer process. They are
for trusted local development and are not sandbox evidence.

An `sdk_module` is visible to the registry and Saga Console for inspection, but
is intentionally not directly runnable through `/v1/modes` or executable in a
flow. The next Phase 2 slice must connect the SDK runner to an isolated sandbox
adapter before generated handlers can enter runtime flows.
