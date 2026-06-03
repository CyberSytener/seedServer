#!/usr/bin/env python3
"""
Test script for Multi-Phase Optimizer

Usage:
    $env:PYTHONPATH='.'; python scripts/test_multi_phase.py
"""

import asyncio
import logging
import os
from pathlib import Path

from app.services.optimizer.optimizer.multi_phase import (
    MultiPhaseOptimizer, PedagogicalIntent
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


async def main():
    # Load .env if present
    repo_root = Path(__file__).parent.parent
    env_path = repo_root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k == "GEMINI_API_KEY":
                    os.environ["GEMINI_API_KEY"] = v
                    print("[+] Loaded GEMINI_API_KEY from .env")

    # Create intent
    intent = PedagogicalIntent(
        description="Spanish A2 lesson on daily greetings and introductions",
        target_lang="Spanish",
        native_lang="English",
        cefr_level="A2",
        topics=["greetings", "introductions", "small talk"],
        focus_areas=["conversational phrases", "politeness", "pronunciation"],
        constraints={
            "exclude_subjunctive": True,
            "prefer_familiar_register": True,
        }
    )

    # Run optimizer
    optimizer = MultiPhaseOptimizer()
    result = await optimizer.optimize(intent)

    print("\n" + "=" * 70)
    print("MULTI-PHASE OPTIMIZATION COMPLETE")
    print("=" * 70)
    print(f"\nSession: {result['session_id']}")
    print(f"\nPhase Results:")
    print(f"  Phase 0: Complete")
    print(f"  Phase 1: Best score {result['phases']['phase_1']['best_score']:.1f}/100")
    print(f"  Phase 2: Best score {result['phases']['phase_2']['best_score']:.1f}/100")
    print(f"  Phase 3: Jury score {result['phases']['phase_3']['jury_score']}/100")


if __name__ == "__main__":
    asyncio.run(main())

