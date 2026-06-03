import asyncio
import logging
import os
from pathlib import Path

from app.services.optimizer.optimizer.manager import OptimizerManager
from app.services.optimizer.optimizer.base import OptimizerVersion, OptimizationTarget, OptimizerTestCase


logging.basicConfig(level=logging.INFO)


def create_mock_test_cases() -> list[OptimizerTestCase]:
    return [
        OptimizerTestCase(
            id="tc_1",
            description="Simple vocabulary lesson",
            target_lang="Spanish",
            native_lang="English",
            cefr_level="A2",
            topic="Greetings",
            focus="vocabulary",
            expected_vocab_count=10,
            expected_dialogue_scenes=2,
            min_score=50,
        ),
        OptimizerTestCase(
            id="tc_2",
            description="Basic translation",
            target_lang="Spanish",
            native_lang="English",
            cefr_level="A2",
            topic="Daily Routines",
            focus="translation",
            expected_vocab_count=8,
            expected_dialogue_scenes=1,
            min_score=50,
        ),
    ]


async def main():
    # Try to load .env from repo root and set GEMINI_API_KEY if present
    repo_root = Path(__file__).parent.parent
    env_path = repo_root / ".env"
    if env_path.exists():
        print(f"Loading environment from {env_path}")
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
                    print("Set GEMINI_API_KEY from .env")
                if k == "SEED_DEFAULT_PROVIDER_BATCH":
                    os.environ["SEED_DEFAULT_PROVIDER_BATCH"] = v
    else:
        print("No .env found at project root; skipping .env load")

    manager = OptimizerManager()

    test_cases = create_mock_test_cases()

    # Run a single-iteration dry run for V1 (prompt-only) using stub LLM
    result_v1 = await manager.run_optimization(
        version=OptimizerVersion.V1_PROMPT_ONLY,
        target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
        test_cases=test_cases,
        max_iterations=1,
    )

    print("\nV1 dry-run complete:")
    print(f" Session: {result_v1.session_id}")
    print(f" Best score: {result_v1.best_iteration.avg_score}/100")
    print(f" Logs: {result_v1.session_id} -> see optimizer_logs folder")


if __name__ == "__main__":
    asyncio.run(main())

