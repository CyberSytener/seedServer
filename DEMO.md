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
- resets `.demo` runtime state for a deterministic reviewer session;
- seeds `market_scan_default` into the gallery.

The Saga Console is a desktop operator interface. Demonstrate it in a browser
window at least 1280px wide.

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

4. `Runs`
   Inspect the flow timeline and the result produced by each connected module.

5. `Modules`
   Run `general_assistant` in stub mode.

6. `Runs`
   Compare the `module` run with the earlier `flow` run.

## What This Demonstrates

- The Gallery stores versioned workflow blueprints.
- Canvas turns a blueprint into a visible graph of contract-compatible modules.
- Sandbox executes the graph deterministically without paid providers.
- Modules can also be invoked independently through the same control plane.
- Runs provides one observable history for both module and flow execution.
- Contract v1, Module SDK, evidence records, and lifecycle gates keep extension
  proposals separate from trusted publication.

For a complete Russian-language presentation script and architecture talking
points, see `docs/PORTFOLIO_DEMO_RUNBOOK_RU.md`.

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

To preserve earlier local demo runs instead of starting clean:

```bash
python scripts/run_portfolio_demo.py --keep-state
```

If you want to run the services manually, see `saga-console/README.md`.

Before publishing the repository, use `docs/PUBLISH_CHECKLIST.md`.

For the platform development direction beyond the reviewer demo, see
`docs/PLATFORM_ROADMAP.md`.
