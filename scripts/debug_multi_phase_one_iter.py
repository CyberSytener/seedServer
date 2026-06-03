#!/usr/bin/env python3
"""
Run one-iteration multi-phase test: Phase0 (intent), Phase1 (1 iter), Phase2 (1 iter), Phase3 (jury)
"""
import asyncio
import os
from pathlib import Path
import logging

from app.services.optimizer.optimizer.multi_phase import (
    MultiPhaseOptimizer, PedagogicalIntent, IntentAnalyzer, BulkDiscovery,
    PrecisionRefinement, JuryAudit
)

logging.basicConfig(level=logging.INFO)

async def main():
    # load .env if present
    repo_root = Path(__file__).parent.parent
    env_path = repo_root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip(); v = v.strip().strip('"').strip("'")
                os.environ[k] = v
        print("[+] Loaded .env")

    intent = PedagogicalIntent(
        description="Spanish A2 lesson on daily greetings and introductions",
        target_lang="Spanish",
        native_lang="English",
        cefr_level="A2",
        topics=["greetings", "introductions", "small talk"],
        focus_areas=["conversational phrases", "politeness", "pronunciation"],
        constraints={"exclude_subjunctive": True}
    )

    # Phase 0
    analyzer = IntentAnalyzer()
    spec = await analyzer.analyze_intent(intent)
    print(f"Phase0: baseline_length={len(spec.baseline_system_instruction)} test_cases={len(spec.test_cases)}")

    # Phase1 (1 iteration)
    discovery = BulkDiscovery(spec)
    phase1 = await discovery.run(max_iterations=1)
    print(f"Phase1: best_score={phase1['best_score']}")

    # Phase2 (1 iteration)
    refinement = PrecisionRefinement(spec, phase1['best_prompt'])
    phase2 = await refinement.run(max_iterations=1)
    print(f"Phase2: best_score={phase2['best_score']}")

    # Phase3 (jury)
    jury = JuryAudit(spec, phase2['best_prompt'])
    phase3 = await jury.run()
    print(f"Phase3: jury_score={phase3['jury_score']}")

    # Save report
    out = repo_root / "optimizer_logs" / "multi_phase_one_iter.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    import json
    out.write_text(json.dumps({
        "phase0": {"baseline_len": len(spec.baseline_system_instruction)},
        "phase1": phase1,
        "phase2": phase2,
        "phase3": phase3,
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Saved report to {out}")

if __name__ == '__main__':
    asyncio.run(main())

