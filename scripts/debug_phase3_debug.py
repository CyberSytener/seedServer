#!/usr/bin/env python3
import asyncio
import json
from app.services.optimizer.optimizer.multi_phase import MultiPhaseOptimizer
from app.services.optimizer.optimizer.base import PedagogicalIntent
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

async def main():
    # Simple test intent
    intent = PedagogicalIntent(
        description="Basic Spanish greetings",
        target_lang="Spanish",
        native_lang="English",
        cefr_level="A2",
        topics=["Greetings", "Introductions"],
        focus_areas=["Social", "Politeness"]
    )
    
    optimizer = MultiPhaseOptimizer()
    
    try:
        print("Starting optimization...")
        result = await optimizer.optimize(intent)
        
        print(json.dumps({
            "phase1_score": result.get("phase1_score"),
            "phase2_score": result.get("phase2_score"),
            "phase3_jury_score": result.get("phase3_jury_score"),
            "phase0_baseline_len": len(result.get("baseline_instruction_text", "")),
        }, indent=2))
        
        # Save for debugging
        Path("/tmp/single_run_result.json").write_text(json.dumps(result, indent=2, default=str))
        print("\nFull result saved to /tmp/single_run_result.json")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

