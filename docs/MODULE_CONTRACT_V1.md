# Module Contract v1

Last updated: 2026-06-07

Module Contract v1 is the active extension boundary for Seed Platform. It gives
humans, AI builders, the registry, and Saga Console one declarative description
of what a module accepts, produces, may access, and costs to execute.

## Canonical Artifacts

- JSON Schema: `app/contracts/module_contract_v1.schema.json`
- Python models and diagnostics: `app/contracts/module_contract.py`
- Runtime registry integration: `app/services/module_registry.py`
- Reference module: `modules/general_assistant.yaml`
- Reference flow blocks: `modules/market_scanner.yaml`,
  `modules/job_scorer.yaml`, and `modules/notification_block.yaml`
- CLI validation: `python scripts/validate_modules.py modules`

The Python validator is the runtime source of truth. The committed JSON Schema
is a portable artifact for editors, generators, and external tooling.

## Required Contract Areas

| Area | Contract fields | Purpose |
| --- | --- | --- |
| Identity | `contract_version`, `mode_id`, `module_version`, `owner`, `lifecycle` | stable naming, ownership, and state |
| Data | `input_schema`, `output_schema`, `errors` | typed request, result, and failure envelopes |
| Execution | `pipeline`, `execution.adapter`, execution limits | runtime route, timeout, retry, idempotency, and determinism |
| Effects | `effects` | declared side effects, compensation, network, and filesystem access |
| Security | `capabilities`, `security` | least-privilege capabilities, secrets, and trust level |
| Dependencies | `dependencies.python`, `compatibility.module_dependencies` | allowed Python packages and module relationships |
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

`capabilities`, `security.secret_refs`, and `dependencies.python` must contain
unique values. Secret and Python dependency declarations describe
requirements; they do not grant access by themselves. The sandbox and publish
gate must provide matching fulfillment evidence.

## Compatibility Rules

The first compatibility checker is intentionally conservative:

1. the consumer must accept the producer's `contract_version`;
2. every required consumer input must be guaranteed by producer output;
3. every declared producer field type must be accepted by the consumer.

The registry exposes this through
`ModuleRegistry.validate_connection(producer_mode_id, consumer_mode_id)`.
Incompatible connections return machine-readable issues and must be rejected
before execution.

## Execution Routes

Contract v1 separates the module's product role from its runtime adapter:

| `pipeline` | Required `execution.adapter` | Direct `/v1/modes` run | Flow graph |
| --- | --- | --- | --- |
| `llm_pipeline` | `saga_orchestrator` | yes | no |
| `flow_block` | `block_registry` | no | yes, when the block is registered |
| `sdk_module` | `module_sdk` | no | no, until the isolated SDK adapter is implemented |

Mismatched declarations fail with `execution.adapter_mismatch`. Saga Console
lists both kinds for inspection, while `/v1/modes` lists only directly runnable
LLM modes. A direct run request for a flow block returns
`module_not_directly_runnable`.

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

The active Gallery path (`market_scanner` -> `job_scorer` ->
`notification_block`) now resolves from Contract v1 manifests. A drift test
requires their declared schemas to match the registered runtime block metadata.
The legacy metadata adapter remains available for blocks that have not yet been
migrated.

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

- Contract v1 supports the active `llm_pipeline` and `flow_block` execution
  routes plus the local-development `sdk_module` route.
- Compatibility checks cover object properties and primitive JSON types, not
  every possible JSON Schema relation.
- Declared effects are validated but observed-vs-declared enforcement belongs
  to the Phase 5 sandbox and publish gate.
- Secret references and external Python dependencies can be declared and
  inspected, but publication remains blocked until verified broker and bundle
  adapters are implemented.
