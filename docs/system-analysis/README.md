# Seed System Analysis Workspace

This directory defines the repeatable process used to inspect `CyberSytener/seedServer` before a large feature, architecture change, promotion decision, or remediation program.

It complements the maintained product documents. It does not replace:

- `SOURCE_OF_TRUTH.md`;
- `docs/ACTIVE_PLATFORM_SCOPE.md`;
- `docs/PLATFORM_ROADMAP.md`;
- `docs/TEST_STRATEGY.md`;
- accepted ADRs;
- feature-specific manifests and implementation plans.

## Why This Exists

The repository contains Active, Candidate, Experimental, and historical surfaces. A deep analysis must distinguish:

1. what documentation declares;
2. what source code currently contains;
3. what tests and CI actually verify;
4. what the reviewer infers from those facts.

Without that separation, an old file can look like a current product commitment, a green workflow can appear to validate more than it really does, or an architecture document can drift away from startup composition and runtime behavior.

## Components

| Path | Responsibility |
| --- | --- |
| `profile.json` | Declared analysis surfaces, exclusions, required documents, hotspot thresholds, and dependency-boundary signals. |
| `ANALYSIS_PROTOCOL.md` | Required evidence classes, analysis stages, scoring, risk handling, and Cold Review rules. |
| `TASK_ROUTE_TEMPLATE.md` | Standard output for converting a target into PR-sized, gate-backed work. |
| `CURRENT_SYSTEM_BASELINE.md` | Human-reviewed starting assessment for the current canonical system. |
| `INVENTORY_FINDINGS.md` | Quantitative repository findings, verified target blockers, readiness verdicts, and the current route. |
| `targets/intent-to-outcome.json` | Current strategic target and immediate checkpoint used by the first route. |
| `scripts/build_system_analysis.py` | Deterministic repository inventory generator. |
| `.github/workflows/system-analysis.yml` | CI execution and downloadable analysis artifact. |

## Generate An Inventory

From the repository root:

```bash
python scripts/build_system_analysis.py
```

The default output directory is ignored runtime output:

```text
system-analysis-artifacts/
  inventory.json
  inventory.md
```

A specific revision label can be supplied when running outside GitHub Actions:

```bash
python scripts/build_system_analysis.py --revision main@<commit-sha>
```

The generated JSON is machine-readable input for comparison tools and future agents. The Markdown file is a compact reviewer view.

## What The Analyzer Observes

The analyzer uses only local repository files and the Python standard library. It records:

- file, extension, top-level directory, size, and line-count inventory;
- Python imports and aggregated package dependency edges;
- FastAPI route decorators and explicit route-registration calls;
- application-composition calls such as `include_router` and `add_middleware`;
- environment-variable names referenced in Python code;
- Pydantic models and `Protocol` interfaces;
- large-file and high-symbol hotspots;
- broad exception handlers, `pass` statements, and TODO markers as review signals;
- configured scope coverage for Active, Candidate, and Experimental surfaces;
- configured dependency-boundary violations;
- quality-gate inventories and GitHub workflow files;
- required maintained documents and ADR files;
- project and dependency metadata from `pyproject.toml`.

It does not execute application imports, call external providers, connect to databases, start containers, inspect user data, or infer runtime correctness from static structure.

## Secret And Artifact Safety

The scanner excludes common sensitive and generated paths by default, including:

- `.env` and `.env.*`;
- private keys and certificate bundles;
- SQLite and local database files;
- logs, archives, coverage output, build output, caches, and `node_modules`;
- repository-specific runtime and artifact directories from `profile.json`.

Only environment-variable **names** referenced in source code are recorded. Values are never read.

## Evidence Labels

Every final analysis must label material findings as one of:

- **Declared** — maintained documentation or an accepted ADR says this is true.
- **Observed** — direct source inspection or generated inventory shows this structure exists.
- **Verified** — a focused test, CI workflow, or reproducible command proves behavior.
- **Inferred** — a reasoned conclusion supported by cited evidence but not directly executed.

An Inferred statement must never be promoted to Verified wording.

## Standard Analysis Run

1. Freeze the canonical ref and target definition.
2. Generate `inventory.json` and `inventory.md`.
3. Read the maintained source-of-truth documents in repository order.
4. Inspect composition roots, contracts, runtime, persistence, policies, external effects, tests, and UI boundaries relevant to the target.
5. Compare declared scope with observed paths and verified gates.
6. Record gaps, contradictions, hidden coupling, safety boundaries, and unknowns.
7. Produce a route using `TASK_ROUTE_TEMPLATE.md`.
8. Perform a read-only Cold Review before calling the route implementation-ready.

## CI Artifact

The `system-analysis` workflow runs the focused analyzer tests, generates the inventory for the PR or `main` commit, validates the JSON, and uploads the two reports as the `seed-system-analysis` artifact.

The workflow is evidence infrastructure. A green result means the inventory could be generated deterministically and the analyzer tests passed. It does **not** mean every repository surface is healthy or production-ready.
