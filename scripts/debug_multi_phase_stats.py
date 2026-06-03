#!/usr/bin/env python
"""
Multi-phase optimizer with statistics collection over multiple runs.

This script runs the full 4-phase optimizer multiple times and collects:
- Phase scores (Phase 0 baseline length, Phase 1/2/3 scores)
- Execution times
- Failure counts
- Average, min, max scores across runs
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from app.services.optimizer.optimizer.multi_phase import (
    MultiPhaseOptimizer, PedagogicalIntent
)

# Load .env for this process
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"[+] Loaded {env_path}")


async def run_single_optimization() -> Dict[str, Any]:
    """Run one complete multi-phase optimization."""
    intent = PedagogicalIntent(
        description="Create Spanish A2 lesson on greetings and introductions",
        target_lang="Spanish",
        native_lang="English",
        cefr_level="A2",
        topics=["greetings", "introductions", "small talk"],
        focus_areas=["conversational fluency", "polite expressions", "cultural awareness"],
        constraints={"max_dialogue_length": 50, "min_vocabulary_size": 15}
    )

    optimizer = MultiPhaseOptimizer()
    start_time = datetime.utcnow()
    
    try:
        result = await optimizer.optimize(intent)
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        
        # Extract scores for statistics
        phase0_baseline_len = result.get("phases", {}).get("phase_0", {}).get("baseline_instruction_length", 0)
        phase1_score = result.get("phases", {}).get("phase_1", {}).get("best_score", 0)
        phase2_score = result.get("phases", {}).get("phase_2", {}).get("best_score", 0)
        phase3_score = result.get("phases", {}).get("phase_3", {}).get("jury_score", 0)
        
        return {
            "success": True,
            "phase0_baseline_len": phase0_baseline_len,
            "phase1_score": phase1_score,
            "phase2_score": phase2_score,
            "phase3_score": phase3_score,
            "elapsed_seconds": elapsed,
            "session_id": optimizer.session_id
        }
    except Exception as e:
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        return {
            "success": False,
            "error": str(e),
            "elapsed_seconds": elapsed
        }


async def main(num_runs: int = 3):
    """Run optimizer multiple times and collect statistics."""
    print(f"\n🚀 Multi-Phase Optimizer Statistics Collection ({num_runs} runs)\n")
    
    runs: List[Dict[str, Any]] = []
    
    for i in range(1, num_runs + 1):
        print(f"[{i}/{num_runs}] Starting run...")
        result = await run_single_optimization()
        runs.append(result)
        
        if result["success"]:
            print(f"  ✓ Phase0: {result['phase0_baseline_len']} chars")
            print(f"    Phase1: {result['phase1_score']:.1f}/100")
            print(f"    Phase2: {result['phase2_score']:.1f}/100")
            print(f"    Phase3: {result['phase3_score']:.1f}/100")
            print(f"    Time: {result['elapsed_seconds']:.1f}s\n")
        else:
            print(f"  ✗ FAILED: {result['error']}\n")
    
    # Compute statistics
    successful_runs = [r for r in runs if r["success"]]
    failed_runs = [r for r in runs if not r["success"]]
    
    print("\n" + "="*70)
    print("STATISTICS SUMMARY")
    print("="*70)
    print(f"Total runs: {len(runs)}")
    print(f"Successful: {len(successful_runs)}")
    print(f"Failed: {len(failed_runs)}")
    
    if successful_runs:
        phase1_scores = [r["phase1_score"] for r in successful_runs]
        phase2_scores = [r["phase2_score"] for r in successful_runs]
        phase3_scores = [r["phase3_score"] for r in successful_runs]
        elapsed_times = [r["elapsed_seconds"] for r in successful_runs]
        
        print("\n--- Phase 1 Scores ---")
        print(f"  Min: {min(phase1_scores):.1f}/100")
        print(f"  Max: {max(phase1_scores):.1f}/100")
        print(f"  Avg: {sum(phase1_scores)/len(phase1_scores):.1f}/100")
        
        print("\n--- Phase 2 Scores ---")
        print(f"  Min: {min(phase2_scores):.1f}/100")
        print(f"  Max: {max(phase2_scores):.1f}/100")
        print(f"  Avg: {sum(phase2_scores)/len(phase2_scores):.1f}/100")
        
        print("\n--- Phase 3 Jury Scores ---")
        print(f"  Min: {min(phase3_scores):.1f}/100")
        print(f"  Max: {max(phase3_scores):.1f}/100")
        print(f"  Avg: {sum(phase3_scores)/len(phase3_scores):.1f}/100")
        
        print("\n--- Execution Time ---")
        print(f"  Min: {min(elapsed_times):.1f}s")
        print(f"  Max: {max(elapsed_times):.1f}s")
        print(f"  Avg: {sum(elapsed_times)/len(elapsed_times):.1f}s")
    
    if failed_runs:
        print("\n--- Failed Runs ---")
        for i, r in enumerate(failed_runs, 1):
            print(f"  {i}. {r.get('error', 'Unknown error')}")
    
    # Save detailed results
    stats_report = {
        "timestamp": datetime.utcnow().isoformat(),
        "num_runs": len(runs),
        "successful": len(successful_runs),
        "failed": len(failed_runs),
        "runs": runs
    }
    
    report_path = Path(__file__).parent.parent / "optimizer_logs" / "multi_phase_stats.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(stats_report, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"\n📊 Detailed report saved to {report_path}\n")
    
    return len(failed_runs) == 0


if __name__ == "__main__":
    import sys
    num_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    success = asyncio.run(main(num_runs))
    sys.exit(0 if success else 1)

