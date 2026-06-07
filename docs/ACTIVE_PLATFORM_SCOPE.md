# Active Platform Scope

Last updated: 2026-06-07

This document defines what Seed Platform currently promises to maintain. The
repository contains a broad historical system, but not every file represents an
active product commitment.

## Scope Levels

### Active

Active surfaces define the current product story and must remain green on every
change.

| Surface | Primary paths | Required evidence |
| --- | --- | --- |
| Portfolio demo launcher | `scripts/run_portfolio_demo.py` | demo smoke |
| Saga Console | `saga-console/` | TypeScript and Vite build |
| Console control plane | `app/api/console/` | console runtime unit tests |
| Module registry and SDK | `modules/`, `app/services/module_registry.py`, `app/module_sdk/`, `app/cli.py` | registry, SDK, and CLI tests |
| Saga execution core | `app/core/realtime/sagas/` | focused saga and simulation tests |
| Stub simulation | `app/sim/`, `tests/unit/sim/` | simulation tests and report |
| Runtime safety baseline | auth, route registration, high-severity Bandit gate | smoke/security/route gates |

Changes to an active surface must include or update focused tests and must pass
the portfolio quality gate.

### Candidate

Candidate surfaces are useful proof points and may become active through an
explicit ADR and test commitment.

- NeoEats domain APIs and blocks.
- Agent session and multi-agent APIs.
- Provider profiles and real-LLM adapters.
- PostgreSQL, Redis, worker, and public deployment integrations.

Candidate code may be used by demos and integration tests, but broad refactors
are not required merely to satisfy historical expectations.

### Experimental

Experimental surfaces are retained for research and discovery. They are not
release blockers unless a task explicitly promotes them.

- broad historical unit suite outside the portfolio gate;
- optimizer experiments and analysis scripts;
- real-provider tests requiring secrets;
- old diagnostic, photo, learning, and batch experiments;
- large historical architecture and audit documents.

Experimental failures must be recorded, but they do not invalidate the
portfolio demo.

### Legacy Or Historical

Legacy material documents previous architecture or development phases. It
must not be treated as the current source of truth.

- dated completion reports and phase summaries;
- archive-dependent verification such as legacy `server_intel`;
- replaced implementations kept only for reference;
- scratch files, generated reports, local databases, and runtime logs.

Legacy code should be removed or moved out of the active repository when its
replacement is verified and the removal can be reviewed independently.

## Promotion Rules

A candidate or experimental surface becomes active only when:

1. its product responsibility is documented;
2. an owner or owning subsystem is named;
3. stable contracts are identified;
4. a focused release-blocking test exists;
5. its failure behavior is defined;
6. an ADR records the decision.

An active surface can be demoted only through an ADR that explains migration
and reviewer impact.

## Dependency Direction

The intended dependency direction for new platform work is:

```text
Saga Console / API
        |
        v
application services and registries
        |
        v
module contracts and runtime interfaces
        |
        v
infrastructure adapters
```

New modules must depend on stable contracts and SDK interfaces. They must not
reach into FastAPI application state or infrastructure internals directly.

## Current Development Boundary

The next active development area is verified secret/dependency fulfillment,
AI repair-loop context assembly, native-operation visibility, and public-key
publication evidence:

- `modules/`
- `app/contracts/module_contract.py`
- `app/module_sdk/`
- `app/cli.py`
- `app/services/module_registry.py`
- `app/services/flow_contract_validator.py`
- contract models and schemas
- contract, SDK, and CLI-focused tests
- console module views when required

Changes outside that boundary require a clear reason and focused verification.
