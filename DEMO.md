# Portfolio Demo Guide

This guide is for reviewers who want to run the project quickly and see the strongest parts without configuring external services.

## One Command

```bash
python -m pip install -e ".[dev]"
python scripts/run_portfolio_demo.py
```

The launcher:

- starts FastAPI in local `test` mode;
- enables deterministic stub providers;
- starts the React Saga Console;
- chooses free local ports if `8000` or `5173` are busy;
- sets `VITE_API_BASE_URL` automatically;
- seeds `market_scan_default` into the gallery.

Credentials:

```text
L0g1n
P@SSW0RD
```

## What To Click

1. `Gallery`
   Open `market_scan_default`.

2. `Canvas`
   Inspect the connected modules and how the flow is represented visually.

3. `Gallery`
   Click `Sandbox` to dry-run the flow. The flow should move to `SANDBOXED`.

4. `Modules`
   Run `general_assistant` in stub mode.

5. `Runs`
   Inspect the run timeline and result.

## Non-Interactive Check

```bash
python scripts/run_portfolio_demo.py --smoke-test --no-open
```

Expected result:

```text
Smoke test passed.
```

## Troubleshooting

If Python dependencies are missing:

```bash
python -m pip install -e ".[dev]"
```

If Node dependencies are missing, the launcher runs `npm install` automatically. To skip that:

```bash
python scripts/run_portfolio_demo.py --skip-install
```

If a port is busy, the launcher selects the next available local port and prints the final URLs.

If you want to run the services manually, see `saga-console/README.md`.

Before publishing the repository, use `docs/PUBLISH_CHECKLIST.md`.
