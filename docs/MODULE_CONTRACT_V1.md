# Module Contract v1

Last updated: 2026-06-06

Module Contract v1 is the active extension boundary for Seed Platform. It gives
humans, AI builders, the registry, and Saga Console one declarative description
of what a module accepts, produces, may access, and costs to execute.

## Canonical Artifacts

- JSON Schema: `app/contracts/module_contract_v1.schema.json`
- Python models and diagnostics: `app/contracts/module_contract.py`
- Runtime registry integration: `app/services/module_registry.py`
- Reference module: `modules/general_assistant.yaml`
- CLI validation: `python scripts/validate_modules.py modules`

The Python validator is the runtime source of truth. The committed JSON Schema
is a portable artifact for editors, generators, and external tooling.

## Required Contract Areas

| Area | Contract fields | Purpose |
| --- | --- | --- |
| Identity | `contract_version`, `mode_id`, `module_version`, `owner`, `lifecycle` | stable naming, ownership, and state |
| Data | `input_schema`, `output_schema`, `errors` | typed request, result, and failure envelopes |
| Execution | `pipeline`, `execution` | timeout, retry, idempotency, and determinism |
| Effects | `effects` | declared side effects, compensation, network, and filesystem access |
| Security | `capabilities`, `security` | least-privilege capabilities, secrets, and trust level |
| Resources | `resources` | memory, concurrency, cost, and provider limits |
| Compatibility | `compatibility` | accepted contract versions and dependencies |
| Evidence | `tests`, `evidence`, prompt/rubric versions | reviewable proof and reproducibility |

## Validation Diagnostics

Validation returns structured issues:

```json
{
  "code": "contract.required",
  "path": "$.execution",
  "message": "Field required"
}
```

The stable `code` and JSON-style `path` are intended for Saga Console and a
future AI repair loop. Human-readable CLI messages are rendered from the same
issues, so runtime and tooling cannot silently diverge.

## Compatibility Rules

The first compatibility checker is intentionally conservative:

1. the consumer must accept the producer's `contract_version`;
2. every required consumer input must be guaranteed by producer output;
3. every declared producer field type must be accepted by the consumer.

The registry exposes this through
`ModuleRegistry.validate_connection(producer_mode_id, consumer_mode_id)`.
Incompatible connections return machine-readable issues and must be rejected
before execution.

## Flow Contract Gate

`FlowContractValidator` applies the same schema guarantees to graph edges. It
resolves schemas from:

- Module Contract v1 manifests in the module registry;
- active legacy block metadata during the migration period.

Every edge must declare an explicit target-to-source field mapping. Compile,
validate, sandbox, run, and release operations reject missing fields,
unguaranteed required outputs, incompatible types, unknown modules, and
modules without a flow execution adapter. The Console API exposes the report as
`contract_validation` or `checks.contract_compatibility`.

This adapter keeps the existing Gallery demo operational while making its
connections enforceable before all blocks have full Contract v1 manifests.

## Legacy Migration

`migrate_legacy_module()` converts an old YAML mapping into a valid draft
Contract v1 manifest. It deliberately assigns:

- lifecycle `draft`;
- trust level `untrusted`;
- conservative resource limits;
- placeholder migration evidence.

The adapter makes old modules inspectable, but does not silently publish or
trust them. A maintainer must review migrated declarations before changing the
lifecycle.

## Current Boundaries

- Only the existing `llm_pipeline` execution pipeline is supported.
- Compatibility checks cover object properties and primitive JSON types, not
  every possible JSON Schema relation.
- Declared effects are validated but observed-vs-declared enforcement belongs
  to the Phase 5 sandbox and publish gate.
