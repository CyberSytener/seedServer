# Test And Quality Strategy

Last updated: 2026-06-07

Seed Platform separates supported release gates from historical and
experimental checks. A green badge must communicate a real promise, not imply
that every experiment in the repository is production-ready.

## Quality Tiers

### Portfolio Gate

Command:

```bash
python scripts/run_quality_gate.py portfolio
```

This is the mandatory local gate for active platform work. It validates the
active documentation links, module registry, Module SDK/CLI, subprocess
sandbox, lifecycle evidence and transition guards, console runtime, modes, auth
provider facade, signed publication gates, security regressions, LLM routing
regression, and simulation unit tests.

Expected properties:

- deterministic;
- no paid provider keys;
- no PostgreSQL or Redis requirement;
- fast enough to run before every commit;
- failure blocks publication.

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
focused active tests when a surface is promoted.

## CI Responsibilities

| Workflow | Responsibility | Blocking |
| --- | --- | --- |
| `lint` | active Python syntax/critical lint and Saga Console build | yes |
| `full-tests` | portfolio unit gate | yes |
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
- a declared active contract;
- module validation or lifecycle behavior;
- runtime safety or authorization;
- a previously observed active-surface regression.

Do not add broad legacy tests to the portfolio gate without first documenting
the product commitment they create.

## Failure Policy

- Fix active gate failures before merging.
- Record experimental failures without disguising them as green.
- Advisory checks must remain visible and include a reason for being advisory.
- A flaky test cannot remain blocking; either remove the source of
  nondeterminism or demote it with an issue and explicit rationale.
