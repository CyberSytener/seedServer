from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PORTFOLIO_TESTS = [
    "tests/unit/test_portfolio_demo_launcher.py",
    "tests/unit/test_console_runtime_api.py",
    "tests/unit/test_auth_providers_api.py",
    "tests/unit/test_module_registry.py",
    "tests/unit/test_module_contract_v1.py",
    "tests/unit/test_module_registry_validation_contract.py",
    "tests/unit/test_module_sdk.py",
    "tests/unit/test_seed_cli.py",
    "tests/unit/test_flow_graph.py",
    "tests/unit/test_flow_contract_validator.py",
    "tests/unit/realtime/test_flow_executor_import_boundary.py",
    "tests/unit/realtime/test_flow_cycle_rejection.py",
    "tests/unit/test_quality_gate_runner.py",
    "tests/unit/test_modes_api.py",
    "tests/unit/test_auth_rate_limit.py",
    "tests/unit/test_security_hardening.py",
    "tests/unit/test_llm_router_openai_regression.py",
    "tests/unit/sim",
]

INTENT_TO_OUTCOME_TESTS = [
    "tests/unit/test_quality_gate_runner.py",
    "tests/unit/opportunity",
    "tests/unit/test_flow_graph.py",
    "tests/unit/test_flow_contract_validator.py",
    "tests/unit/realtime/test_flow_executor_import_boundary.py",
    "tests/unit/realtime/test_flow_cycle_rejection.py",
    "tests/integration/opportunity",
]

GATE_CHOICES = (
    "portfolio",
    "intent-to-outcome",
    "integration",
    "experimental",
)


def _run(command: list[str]) -> int:
    print(f"\n> {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def _pytest(paths: list[str]) -> int:
    return _run([sys.executable, "-m", "pytest", "-q", "--timeout=120", "--no-cov", *paths])


def _run_docs_then_tests(paths: list[str]) -> int:
    docs_result = _run([sys.executable, "scripts/validate_active_docs.py"])
    if docs_result:
        return docs_result
    return _pytest(paths)


def run_gate(gate: str) -> int:
    if gate == "portfolio":
        return _run_docs_then_tests(PORTFOLIO_TESTS)
    if gate == "intent-to-outcome":
        return _run_docs_then_tests(INTENT_TO_OUTCOME_TESTS)
    if gate == "integration":
        return _pytest(["tests/integration"])
    if gate == "experimental":
        print("Experimental gate is diagnostic and may expose known legacy failures.")
        return _pytest(["tests/unit"])
    raise ValueError(f"Unknown gate: {gate}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a documented Seed Platform quality gate.")
    parser.add_argument("gate", choices=GATE_CHOICES)
    args = parser.parse_args()
    return run_gate(args.gate)


if __name__ == "__main__":
    raise SystemExit(main())
