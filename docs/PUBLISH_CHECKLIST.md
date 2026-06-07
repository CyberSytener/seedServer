# Portfolio Publish Checklist

Use this checklist before sharing the repository link with reviewers.

## Must Pass

```bash
python scripts/run_portfolio_demo.py --smoke-test --no-open
python scripts/run_quality_gate.py portfolio
cd saga-console && npm run build
```

Expected:

- demo smoke prints `Smoke test passed`;
- Saga Console build completes without chunk-size warnings;
- backend focused tests pass.
- the documented portfolio quality gate passes.

## Reviewer Path

1. Start with `README.md`.
2. Run `python scripts/run_portfolio_demo.py`.
3. Log in with `L0g1n / P@SSW0RD`.
4. Open `Gallery`.
5. Open `market_scan_default` on Canvas.
6. Run `Sandbox`.
7. Open `Runs` and inspect the timeline.
8. Open `Modules` and run `general_assistant` in stub mode.

## Suggested Screenshots

- Saga Console Gallery with the `Portfolio Demo` panel.
- Canvas showing `market_scan_default`.
- Runs detail view after sandbox execution.
- Modules view with `general_assistant` stub result.
- Root README quick demo section.

## Do Not Publish

Keep these out of the public branch or release archive:

- `.env`, `.env.public`, `.env.local`;
- any real `SEED_MODULE_EVIDENCE_SIGNING_KEY` value;
- `seed.db`, `*.db-wal`, `*.db-shm`, `*.sqlite3`;
- `node_modules/`, `saga-console/dist/`;
- `logs/`, `reports/baseline/`, `test_artifacts/`, `optimizer_logs/`;
- local tunnel configs under `cloudflared/`;
- historical scratch files that are not part of the reviewer path.

## Public Framing

Recommended GitHub description:

```text
FastAPI AI orchestration backend with saga workflows, module runtime APIs, NeoEats domain automation, and a React visual Saga Console.
```

Recommended short pitch:

```text
Seed Server is a portfolio demo of an AI workflow control plane: FastAPI backend, saga execution model, scoped runtime APIs, and a React operator console for visual flow inspection and stub-mode runs.
```

## Known Demo Boundaries

- The default demo uses deterministic stub providers.
- Real LLM calls require provider keys and are intentionally outside the reviewer path.
- Docker Compose remains available, but the portfolio demo does not require Docker.
- The optional Module SDK Docker adapter is built and smoke-tested in CI; local
  use requires a running Docker engine.
- Some deeper architecture documents are historical. Prefer `README.md`, `DEMO.md`, and `docs/PORTFOLIO_GITHUB_BRIEF.md` as public entry points.
- Platform development direction is defined in `docs/PLATFORM_ROADMAP.md`; active
  commitments are defined in `docs/ACTIVE_PLATFORM_SCOPE.md`.
