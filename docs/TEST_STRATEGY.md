# Test And Quality Strategy

Last updated: 2026-07-17

Seed Platform separates supported release gates from Candidate and historical
checks. A green badge must communicate a real promise, not imply that every
experiment in the repository is production-ready.

## Quality Tiers

### Portfolio Gate

Command:

```bash
python scripts/run_quality_gate.py portfolio
```

This is the mandatory local gate for active platform work. It validates the
active documentation links, module registry, Module SDK/CLI, subprocess
sandbox, Docker adapter command policy, lifecycle evidence and transition
guards, operation-level capability violations, fail-closed secret/dependency
publication policy, console runtime, modes, auth provider facade, signed
publication gates, security regressions, LLM routing regression, active flow
graph safety, and simulation unit tests.

Candidate-only tests do not belong in the portfolio gate unless they also
protect an already Active runtime or authorization invariant.

Expected properties:

- deterministic;
- no paid provider keys;
- no PostgreSQL or Redis requirement;
- no Docker daemon requirement; hardened adapter tests use a deterministic
  command-runner fixture;
- fast enough to run before every commit;
- failure blocks changes to the Active platform surface.

### Intent-to-Outcome Candidate Gate

Command:

```bash
python scripts/run_quality_gate.py intent-to-outcome
```

This is the focused release gate for the Intent-to-Outcome Candidate surface
governed by ADR 0015. It does not promote the surface to Active. It provides a
separate, explicit promise for changes under the Candidate package, fixture,
contract, flow-safety, and test boundaries.

The gate validates maintained documentation first, then runs:

- the quality-gate inventory and fail-fast tests;
- `tests/unit/opportunity/`;
- deterministic flow graph and contract validation tests;
- canonical FlowExecutor import and cycle-rejection safety tests;
- `tests/integration/opportunity/`.

Expected properties:

- deterministic and fixture-first;
- no paid provider keys or live external sources;
- no Redis or PostgreSQL requirement;
- no Docker daemon requirement;
- no real financial, public, physical, or privacy-sensitive action;
- fast enough for every Candidate pull request;
- failure blocks changes to the Intent-to-Outcome Candidate surface.

GitHub Actions runs this command through the path-scoped
`intent-to-outcome-tests` workflow whenever the Candidate surface, its governing
documents, its flow-safety dependencies, its tests, or the workflow itself
changes.

### Integration Gate

Command:

```bash
python scripts/run_quality_gate.py integration
```

This runs `tests/integration/`. GitHub Actions supplies Redis and PostgreSQL
where needed. Locally, tests that need unavailable services may require the
Docker development stack.

Expected properties:

- exercises cross-module and API behavior;
- uses stub providers by default;
- failure blocks changes to active integration behavior.

### Demo Smoke

Command:

```bash
python scripts/run_portfolio_demo.py --smoke-test --no-open
```

This verifies the reviewer path end to end: local backend, frontend, auth,
gallery seed, sandbox flow, module run, and frontend availability.

### Experimental Gate

Command:

```bash
python scripts/run_quality_gate.py experimental
```

This runs the broad historical unit suite. It is intentionally not a release
gate yet. Failures are useful cleanup signals and should be converted into
focused Active or Candidate tests when a surface is promoted or formalized.

## CI Responsibilities

| Workflow | Responsibility | Blocking |
| --- | --- | --- |
| `lint` | active Python syntax/critical lint, Saga Console build, and Docker module sandbox build/smoke | yes |
| `full-tests` | portfolio unit gate | yes |
| `intent-to-outcome-tests` | path-scoped Intent-to-Outcome Candidate gate | yes when triggered |
| `integration-tests` | supported integration scenarios | yes |
| `smoke-tests` | auth/security/runtime regression smoke | yes |
| `simulation-tests` | deterministic simulation runtime | yes when triggered |
| `route-registration-sanity` | API route registration | yes when triggered |
| `security-gates` | runtime dependency presence and high-severity static findings | yes |
| dependency audit inside `security-gates` | dependency upgrade signal | advisory |
| `real-llm-smoke` | secrets-gated provider confidence | conditional |
| `server-intel-drift` | legacy archive compatibility | conditional |

## Adding A Release-Blocking Test

A test belongs in the portfolio gate when it protects:

- the reviewer demo;
- a declared Active contract;
- module validation or lifecycle behavior;
- runtime safety or authorization;
- a previously observed Active-surface regression.

A test belongs in the Intent-to-Outcome Candidate gate when it protects:

- the universal Candidate contracts or deterministic policies;
- Candidate package and dependency boundaries;
- Candidate fixture or reference-flow behavior;
- flow-safety behavior required by the Candidate architecture;
- a previously observed Candidate regression.

Candidate tests move into the portfolio gate only when a promotion ADR makes the
corresponding behavior Active, or when the test also protects an existing Active
runtime safety invariant.

Do not add broad legacy tests to a blocking gate without first documenting the
product commitment they create.

## Failure Policy

- Fix portfolio gate failures before merging Active platform changes.
- Fix Intent-to-Outcome gate failures before merging changes to that Candidate
  surface.
- Fix integration failures before merging changes to supported integration
  behavior.
- Record experimental failures without disguising them as green.
- Advisory checks must remain visible and include a reason for being advisory.
- A flaky test cannot remain blocking; either remove the source of
  nondeterminism or demote it with an issue and explicit rationale.
