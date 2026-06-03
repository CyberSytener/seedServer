# Saga Console

React console for inspecting modules, seeding gallery flows, opening flows on the canvas, sandboxing drafts, and launching stub or real runs through the Seed Server console facade.

For the portfolio demo, prefer the repository-level launcher:

```powershell
python scripts/run_portfolio_demo.py
```

## Local demo

Start the backend from the repository root:

```powershell
$env:SEED_ENV = "test"
$env:SEED_TEST_AUTH_MODE = "1"
$env:SEED_API_KEY_PEPPER = "local_demo_pepper"
$env:SEED_ENABLE_STUB = "1"
$env:SEED_DEV_CORS = "1"
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Start the console:

```powershell
cd saga-console
npm install
npm run dev
```

Open `http://127.0.0.1:5173` and use the built-in demo credentials:

```text
L0g1n
P@SSW0RD
```

For `npm run preview` or static hosting, build with `VITE_API_BASE_URL=http://127.0.0.1:8000` because the Vite dev proxy is not available in preview mode.
