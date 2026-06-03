# Seed Server

Seed Server is a portfolio demo of an AI workflow orchestration platform built with FastAPI and React.

The project demonstrates a backend control plane for running modular AI workflows: flows can be created, inspected, sandboxed, executed in deterministic stub mode, and reviewed through a visual Saga Console. The goal of the project is to show backend architecture, workflow runtime design, scoped API surfaces, and a practical operator UI rather than to present a polished commercial SaaS product.

_ Highlights _

- FastAPI backend with modular API routing
- Saga-style workflow execution model
- Module and flow runtime APIs
- Visual React Saga Console built with Vite and TypeScript
- Gallery, Canvas, Modules, Runs, and Provider views
- Deterministic stub mode for local demo without paid LLM keys
- Demo launcher for one-command local startup
- NeoEats domain layer showing how real product workflows can be built on top of the runtime
- Auth, scoped permissions, public-mode safety checks, and focused test coverage

## Demo

bash

python scripts/run_portfolio_demo.py

The launcher starts the backend and Saga Console locally, seeds a demo workflow, and opens the UI.

Demo credentials:

"L0g1n / P@SSW0RD"

Recommended review path:

Open Gallery
Open market_scan_default
Inspect the flow on Canvas
Run Sandbox
Open Runs and inspect the execution timeline
Open Modules and run general_assistant in stub mode
Tech Stack
Python, FastAPI, Pydantic
React, TypeScript, Vite
Zustand, React Flow
SQLite for local/demo storage
Stub LLM provider for deterministic local runs
Optional Redis/PostgreSQL/Docker stack for extended development
Why This Project Matters
This project was built to explore how AI workflows can be treated as observable, testable backend processes rather than one-off prompt calls. It focuses on orchestration, runtime contracts, safety boundaries, and developer-facing tooling.

It is intentionally packaged as a portfolio demo: easy to launch, safe to run locally, and designed to make the architecture visible through both API tests and a visual console.


**GitHub Topics**
```text
fastapi
python
react
typescript
vite
workflow-engine
ai-orchestration
saga-pattern
react-flow
llmops
portfolio-project
backend
