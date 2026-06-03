from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.sim.harness import run_simulation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Seed simulation harness")
    parser.add_argument("--output-dir", default=".seed_artifacts/simulation", help="Directory for simulation artifacts and report")
    parser.add_argument("--no-modes", action="store_true", help="Skip S4 modes scenario")
    parser.add_argument(
        "--llm-mode",
        choices=["stub", "real"],
        default=os.getenv("SIM_LLM_MODE", "stub"),
        help="LLM adapter mode for S4 simulation (default: SIM_LLM_MODE env or stub)",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["gemini", "openai"],
        default=os.getenv("SIM_LLM_PROVIDER"),
        help="Optional real-mode provider override for S4 (gemini/openai)",
    )
    parser.add_argument(
        "--llm-model",
        default=os.getenv("SIM_LLM_MODEL"),
        help="Optional real-mode model override for S4 (e.g. gemini-2.0-flash-lite)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = run_simulation(
        output_dir=output_dir,
        include_modes=not args.no_modes,
        llm_mode=args.llm_mode,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
    )
    report_path = output_dir / f"{report.run_id}.json"
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    status = "PASS" if report.passed else "FAIL"
    print(f"Simulation Harness: {status} ({report.passed_count}/{report.scenario_count})")
    print(f"Report: {report_path}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
