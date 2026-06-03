"""
Auto-Optimizer Mode (AOM) - Iterative System Prompt Refinement

Technical Specification Implementation:
- Versioned prompt sandbox with history tracking
- Structured stress-testing with diverse edge cases
- Meta-optimization loop using Gemini 2.5 Pro
- State management for resumption capability
- Token management (prompts under 1500 tokens)
- Non-destructive approach (uses composition over modification)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.pipeline.pipeline.steps import LessonPlannerStep as LessonPlanner, LessonContentStep as ContentCreator, LessonValidatorStep as Validator
from app.services.pipeline.pipeline.core import PipelineContext, PipelineOrchestrator
from app.infrastructure.llm.client import get_llm_client
from app.services.lesson.engine import GENERATOR_PROMPT, GENERATOR_PROMPT_COMPACT
from app.settings import get_settings

logger = logging.getLogger(__name__)


# ============================================================================
# PATHS AND CONSTANTS
# ============================================================================

ROOT_DIR = Path(__file__).parent.parent
PROMPTS_HISTORY_DIR = ROOT_DIR / "prompts" / "history"
OPTIMIZER_LOGS_DIR = ROOT_DIR / "optimizer_logs"
TEST_CASES_PATH = ROOT_DIR / "test_cases.json"
OPT_LOG_PATH = ROOT_DIR / "optimization_log.json"
OPT_REPORT_PATH = ROOT_DIR / "optimization_report.md"

STABILITY_THRESHOLD = 95
TOKEN_LIMIT = 1500
MAX_ITERATIONS = 10


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class TestCase:
    """Structured test case for stress testing"""
    id: str
    description: str
    target_lang: str
    native_lang: str
    cefr_level: str
    topic: str
    focus: str
    expected_vocab_count: int
    expected_dialogue_scenes: int
    min_score: int


@dataclass
class TestResult:
    """Result from a single test case execution"""
    test_case_id: str
    duration_s: float
    validation: Dict[str, Any]
    score: int
    issues: List[str]
    passed: bool
    vocab_count: int
    dialogue_count: int
    events: List[Dict[str, Any]]
    lesson_content: Dict[str, Any]  # Full generated lesson content
    lesson_content_raw: str         # Raw LLM response text


@dataclass
class PromptVersion:
    """A versioned system prompt"""
    version: int
    timestamp: int
    prompt_text: str
    token_count: int
    avg_score: float
    test_results: List[TestResult]
    filename: str


# ============================================================================
# PROMPT LOADER
# ============================================================================

class PromptLoader:
    """Manages prompt versioning and loading"""
    
    @staticmethod
    def save_version(version: int, prompt: str, avg_score: float) -> Path:
        """Save a prompt version to history"""
        PROMPTS_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        
        filename = f"creator_v{version}_{int(avg_score)}.txt"
        filepath = PROMPTS_HISTORY_DIR / filename
        
        filepath.write_text(prompt, encoding="utf-8")
        logger.info(f"Saved prompt version {version} to {filepath}")
        
        return filepath
    
    @staticmethod
    def load_version(version: int) -> Optional[str]:
        """Load a specific prompt version"""
        pattern = f"creator_v{version}_*.txt"
        matches = list(PROMPTS_HISTORY_DIR.glob(pattern))
        
        if matches:
            return matches[0].read_text(encoding="utf-8")
        return None
    
    @staticmethod
    def get_latest_version() -> Tuple[int, Optional[str]]:
        """Get the latest prompt version number and content"""
        if not PROMPTS_HISTORY_DIR.exists():
            return 0, None
        
        versions = []
        for f in PROMPTS_HISTORY_DIR.glob("creator_v*_*.txt"):
            try:
                v = int(f.stem.split("_")[1].replace("v", ""))
                versions.append((v, f))
            except (IndexError, ValueError):
                continue
        
        if not versions:
            return 0, None
        
        versions.sort(reverse=True)
        latest_v, latest_file = versions[0]
        
        return latest_v, latest_file.read_text(encoding="utf-8")


# ============================================================================
# CONTENT CREATOR WITH PROMPT OVERRIDE
# ============================================================================

class ContentCreatorWithOverride(ContentCreator):
    """ContentCreator that accepts a custom system prompt"""
    
    def __init__(self, override_prompt: Optional[str] = None):
        super().__init__()
        self.override_prompt = override_prompt
    
    async def execute(self, ctx: PipelineContext) -> None:
        """Execute with optional prompt override"""
        # If an override prompt is provided, run content generation here
        if self.override_prompt:
            await self._emit_start(ctx, "Crafting engaging lesson content (override)...")

            # Ensure lesson_plan is present
            plan = ctx.get("lesson_plan")
            if not plan:
                await self._emit_error(ctx, "No lesson plan found in context for ContentCreatorWithOverride")
                raise ValueError("No lesson plan found in context")

            target_lang = ctx.get("target_lang", "Spanish")
            native_lang = ctx.get("native_lang", "English")
            cefr_level = ctx.get("cefr_level", "A2")

            # Build task descriptions if not present
            task_descriptions = plan.get("task_descriptions", [])
            if not task_descriptions:
                task_descriptions = [
                    "Task 1: [MCQ] Vocabulary recognition - core words",
                    "Task 2: [MCQ] Vocabulary recognition - context-based",
                    "Task 3: [MCQ] Vocabulary recognition - advanced synonyms",
                    "Task 4: [Translation] Basic phrase translation",
                    "Task 5: [Translation] Dialogue line translation",
                    "Task 6: [Translation] Complex sentence translation",
                    "Task 7: [Word Bank] Sentence construction with word ordering",
                    "Task 8: [Word Bank] Grammar application in context",
                    "Task 9: [Listening Mimic] Pronunciation practice - common greeting",
                    "Task 10: [Listening Mimic] Pronunciation practice - dialogue exchange"
                ]

            # Build user prompt with Exercise Diversity directive
            user_prompt = f"""You are a creative language learning content writer.

Based on this lesson plan:
{json.dumps(plan, indent=2)}

Create engaging lesson content for {target_lang} learners (CEFR {cefr_level}).

MANDATORY EXERCISE DIVERSITY DIRECTIVE:
Generate EXACTLY 10 exercises with this distribution:
- Tasks 1-3: Multiple Choice (MCQ) - One correct answer, three plausible distractors
- Tasks 4-6: Translation - Provide source text and exact target translation
- Tasks 7-8: Word Bank - Scrambled words that user reorders to match English sentence
- Tasks 9-10: Listening Mimic - Dialogue line focusing on pronunciation (include Romaji for Japanese)

Task Guidance:
{chr(10).join(task_descriptions)}

Return ONLY a JSON object:
{{
  "lessonId": "lesson_unique_id",
  "mode": "comprehensive",
  "targetLang": "{target_lang}",
  "nativeLang": "{native_lang}",
  "level": "{cefr_level}",
  "title": "{plan.get('lessonTitle', 'Untitled')}",
  "exercises": [
    {{exercise_1}},
    {{exercise_2}},
    ... (exactly 10 exercises, task_1 through task_10)
  ]
}}

CRITICAL REQUIREMENTS:
- EXACTLY 10 exercises (task_1 through task_10)
- All 10 must have unique ids
- Tasks 1-3: type="mcq" (each with 4 choices, correctChoiceIndex, correctAnswer, tip)
- Tasks 4-6: type="translation" (each with sourceText, sourceLang, targetLang, correctAnswer, acceptedVariants, tip)
- Tasks 7-8: type="word_bank" (each with englishSentence, tokens array, scrambledText, correctSentence, tip)
- Tasks 9-10: type="listening_mimic" (each with dialogue, romaji, english, focus, correctPronunciation, tip)

Make it authentic, natural, and fun. Use real conversational language."""

            settings = get_settings()
            llm_client = await get_llm_client()

            provider = settings.default_provider_batch or "stub"
            if provider in ("gemini", "openai") and not (
                (provider == "gemini" and settings.gemini_api_key) or
                (provider == "openai" and settings.openai_api_key)
            ):
                provider = "stub"

            try:
                llm_resp = await llm_client.generate(
                    system_prompt=self.override_prompt,
                    user_prompt=user_prompt,
                    provider=provider,
                    model=settings.gemini_model_batch,
                    max_tokens=8000
                )

                response_text = llm_resp.text
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    content = json.loads(response_text[json_start:json_end])
                    ctx.set("lesson_content", content)
                    # Save raw response as well for debugging/archival
                    ctx.set("lesson_content_raw", response_text)

                    exercise_count = len(content.get("exercises", []))

                    await self._emit_complete(
                        ctx,
                        f"Content created: {exercise_count} exercises (3 MCQ, 3 Translation, 2 Word Bank, 2 Listening)",
                        {"exercise_count": exercise_count}
                    )
                else:
                    await self._emit_error(ctx, "No valid JSON in response from override ContentCreator")
                    raise ValueError("No valid JSON in response")

            except Exception as e:
                await self._emit_error(ctx, str(e))
                raise
        else:
            await super().execute(ctx)


# ============================================================================
# META REFINER
# ============================================================================

class MetaRefiner:
    """Uses Gemini 2.5 Pro to refine system prompts based on validation feedback"""
    
    def __init__(self):
        self.settings = get_settings()
        self.provider = "gemini" if self.settings.gemini_api_key else "stub"
        self.model = self.settings.gemini_model_batch  # Use Gemini 2.5 Pro
    
    async def refine_prompt(
        self,
        current_prompt: str,
        failures: List[TestResult],
        successes: List[TestResult],
        iteration: int
    ) -> str:
        """
        Analyze failures and successes, then generate an improved prompt.
        
        Args:
            current_prompt: The current system prompt being tested
            failures: Test results with scores < 90
            successes: Test results with scores >= 95
            iteration: Current iteration number
            
        Returns:
            Improved system prompt text
        """
        llm_client = await get_llm_client()
        
        # Build analysis context
        failure_summary = self._build_failure_summary(failures)
        success_summary = self._build_success_summary(successes)
        
        meta_prompt = f"""You are an expert prompt engineer specializing in language learning content generation.

**CURRENT SYSTEM PROMPT (Iteration {iteration}):**
```
{current_prompt[:800]}...
```

**PERFORMANCE ANALYSIS:**

Failures (Score < 90): {len(failures)} cases
{failure_summary}

Successes (Score >= 95): {len(successes)} cases  
{success_summary}

**YOUR TASK:**
Analyze why failures occurred (e.g., truncation, inappropriate tone, CEFR level mismatch, vocabulary/dialogue count errors).
Output an improved system prompt that:
1. Retains successful traits from high-scoring cases
2. Fixes specific failure patterns identified above
3. Is under {TOKEN_LIMIT} tokens
4. Maintains pedagogical soundness

**CRITICAL CONSTRAINTS:**
- Must be a complete, standalone system prompt
- No markdown formatting, just the raw prompt text
- Focus on actionable instructions for the LLM
- Address the specific failure patterns

Return ONLY the improved prompt text, no commentary."""

        try:
            resp = await llm_client.generate(
                system_prompt="You are an expert prompt engineer for language-learning LLMs.",
                user_prompt=meta_prompt,
                provider=self.provider,
                model=self.model,
                max_tokens=3000,
            )
            
            improved = resp.text.strip()
            
            # Remove markdown if present
            if improved.startswith("```"):
                lines = improved.split("\n")
                improved = "\n".join(lines[1:-1]) if len(lines) > 2 else improved
            
            # Truncate if needed
            token_count = len(improved.split())
            if token_count > TOKEN_LIMIT:
                words = improved.split()[:TOKEN_LIMIT]
                improved = " ".join(words) + "..."
                logger.warning(f"Truncated prompt from {token_count} to {TOKEN_LIMIT} tokens")
            
            return improved
            
        except Exception as e:
            logger.error(f"Meta-refinement failed: {e}")
            return current_prompt  # Return unchanged on error
    
    def _build_failure_summary(self, failures: List[TestResult]) -> str:
        """Build a summary of failure patterns"""
        if not failures:
            return "None"
        
        summary_parts = []
        for result in failures[:3]:  # Top 3 failures
            summary_parts.append(
                f"- {result.test_case_id}: Score {result.score}/100\n"
                f"  Issues: {', '.join(result.issues) if result.issues else 'No specific issues'}\n"
                f"  Vocab: {result.vocab_count}, Dialogues: {result.dialogue_count}"
            )
        
        return "\n".join(summary_parts)
    
    def _build_success_summary(self, successes: List[TestResult]) -> str:
        """Build a summary of success patterns"""
        if not successes:
            return "None"
        
        avg_score = sum(r.score for r in successes) / len(successes)
        return f"Average score: {avg_score:.1f}/100 across {len(successes)} cases"


# ============================================================================
# STATE MANAGER
# ============================================================================

class StateManager:
    """Manages optimization state for resumption capability"""
    
    @staticmethod
    def save_state(iteration: int, prompt_versions: List[PromptVersion]) -> None:
        """Save current optimization state"""
        state = {
            "last_iteration": iteration,
            "timestamp": int(time.time()),
            "versions": [
                {
                    "version": v.version,
                    "avg_score": v.avg_score,
                    "token_count": v.token_count,
                    "filename": v.filename,
                    "test_count": len(v.test_results),
                    "passed_count": sum(1 for r in v.test_results if r.passed)
                }
                for v in prompt_versions
            ]
        }
        
        OPT_LOG_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        logger.info(f"State saved at iteration {iteration}")
    
    @staticmethod
    def load_state() -> Optional[Dict[str, Any]]:
        """Load saved optimization state"""
        if not OPT_LOG_PATH.exists():
            return None
        
        try:
            return json.loads(OPT_LOG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
            return None


# ============================================================================
# TEST EXECUTOR
# ============================================================================

async def execute_test_case(
    test_case: TestCase,
    system_prompt: str,
    prompt_version: int
) -> TestResult:
    """Execute a single test case with the given prompt"""
    
    ctx = PipelineContext({
        "target_lang": test_case.target_lang,
        "native_lang": test_case.native_lang,
        "cefr_level": test_case.cefr_level,
        "topic": test_case.topic,
        "focus": test_case.focus,
        "prompt_version": prompt_version,
    })
    
    # Use custom ContentCreator with prompt override
    steps = [
        LessonPlanner(),
        ContentCreatorWithOverride(override_prompt=system_prompt),
        Validator()
    ]
    orchestrator = PipelineOrchestrator(steps)
    
    start = time.time()
    try:
        await orchestrator.run(ctx)
    except Exception as e:
        logger.warning(f"Test case {test_case.id} failed: {e}")
    
    duration = time.time() - start
    
    # Extract results
    validation = ctx.get("validation_result") or {}
    content = ctx.get("lesson_content") or {}
    raw_response = ctx.get("lesson_content_raw") or ""
    
    score = validation.get("score", 0) if isinstance(validation, dict) else 0
    issues = validation.get("issues", []) if isinstance(validation, dict) else []
    
    vocab_count = len(content.get("vocabulary", [])) if isinstance(content, dict) else 0
    dialogue_count = len(content.get("dialogues", [])) if isinstance(content, dict) else 0
    
    passed = (
        score >= test_case.min_score and
        len(issues) == 0
    )
    
    return TestResult(
        test_case_id=test_case.id,
        duration_s=duration,
        validation=validation,
        score=score,
        issues=issues,
        passed=passed,
        vocab_count=vocab_count,
        dialogue_count=dialogue_count,
        events=[
            {"step": ev.step_name, "status": ev.status, "message": ev.message}
            for ev in ctx.events
        ],
        lesson_content=content if isinstance(content, dict) else {},
        lesson_content_raw=raw_response if isinstance(raw_response, str) else ""
    )


# ============================================================================
# REPORT GENERATOR
# ============================================================================

class ReportGenerator:
    """Generates final optimization report"""
    
    @staticmethod
    def generate(prompt_versions: List[PromptVersion]) -> str:
        """Generate markdown report"""
        if not prompt_versions:
            return "# Optimization Report\n\nNo data available."
        
        first = prompt_versions[0]
        last = prompt_versions[-1]
        
        report = f"""# Auto-Optimizer Mode (AOM) - Final Report

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**Total Iterations:** {len(prompt_versions)}  
**Optimization Goal:** Achieve {STABILITY_THRESHOLD}+ score across diverse test cases

---

## Executive Summary

- **Initial Average Score:** {first.avg_score:.1f}/100
- **Final Average Score:** {last.avg_score:.1f}/100  
- **Improvement Delta:** {last.avg_score - first.avg_score:+.1f} points
- **Best Performing Version:** v{max(prompt_versions, key=lambda v: v.avg_score).version} ({max(v.avg_score for v in prompt_versions):.1f}/100)

---

## Evolution Path

"""
        
        for v in prompt_versions:
            passed = sum(1 for r in v.test_results if r.passed)
            total = len(v.test_results)
            
            report += f"""### Version {v.version} (Score: {v.avg_score:.1f}/100)
- **Tests Passed:** {passed}/{total}
- **Token Count:** {v.token_count}
- **Saved As:** `{v.filename}`

"""
        
        # Add golden prompt
        golden = max(prompt_versions, key=lambda v: v.avg_score)
        report += f"""---

## The Golden Prompt (Version {golden.version})

```
{golden.prompt_text}
```

**Performance Metrics:**
- Average Score: {golden.avg_score:.1f}/100
- Tests Passed: {sum(1 for r in golden.test_results if r.passed)}/{len(golden.test_results)}
- Token Count: {golden.token_count}

---

## Test Results Breakdown

"""
        
        for i, result in enumerate(golden.test_results, 1):
            status = "✅ PASS" if result.passed else "❌ FAIL"
            report += f"""### Test {i}: {result.test_case_id}
- **Status:** {status}
- **Score:** {result.score}/100
- **Vocab Count:** {result.vocab_count}
- **Dialogue Count:** {result.dialogue_count}
- **Issues:** {', '.join(result.issues) if result.issues else 'None'}

"""
        
        return report


async def _run_single_pipeline(system_prompt: str, run_index: int) -> Dict[str, Any]:
    ctx = PipelineContext({
        "target_lang": "Spanish",
        "native_lang": "English",
        "cefr_level": "A2",
        "topic": "Optimization Test",
        "focus": "grammar",
    })

    steps = [LessonPlanner(), ContentCreator(), Validator()]
    orchestrator = PipelineOrchestrator(steps)

    start = time.time()
    try:
        # The step implementations use get_llm_client() internally and respect prompts
        await orchestrator.run(ctx)
    except Exception as e:
        logger.warning(f"Pipeline run {run_index} failed gracefully: {e}")
        ctx.add_error(str(e))

    duration = time.time() - start

    validation = ctx.get("validation_result") or {}
    issues = validation.get("issues") if isinstance(validation, dict) else []

    return {
        "run": run_index,
        "duration_s": duration,
        "validation": validation,
        "validation_issues": issues or [],
        "events": [ {"step": ev.step_name, "status": ev.status, "message": ev.message} for ev in ctx.events ],
    }


# ============================================================================
# MAIN OPTIMIZATION ENGINE
# ============================================================================

async def run_optimization(
    max_iterations: int = MAX_ITERATIONS,
    resume: bool = False,
    test_cases_file: str = "test_cases.json"
) -> List[PromptVersion]:
    """
    Main optimization loop implementing the AOM specification.
    
    Args:
        max_iterations: Maximum number of refinement iterations
        resume: Whether to resume from saved state
        test_cases_file: Path to test cases JSON file
        
    Returns:
        List of prompt versions with their test results
    """
    settings = get_settings()
    
    # Create session log directory
    session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_log_dir = OPTIMIZER_LOGS_DIR / f"session_{session_timestamp}"
    session_log_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Session logs will be saved to: {session_log_dir}")
    
    # Load test cases
    test_cases_path = ROOT_DIR / test_cases_file
    if not test_cases_path.exists():
        raise FileNotFoundError(f"Test cases file not found: {test_cases_path}")
    
    test_cases_data = json.loads(test_cases_path.read_text(encoding="utf-8"))
    test_cases = [TestCase(**tc) for tc in test_cases_data["test_cases"]]
    
    logger.info(f"Loaded {len(test_cases)} test cases")
    
    # Initialize
    meta_refiner = MetaRefiner()
    prompt_versions: List[PromptVersion] = []
    
    # Get initial prompt
    start_iteration = 1
    current_prompt = GENERATOR_PROMPT_COMPACT if settings.optimize_mode else GENERATOR_PROMPT
    
    if not current_prompt:
        current_prompt = "You are a helpful lesson planner. Return JSON as specified."
    
    # Resume from state if requested
    if resume:
        state = StateManager.load_state()
        if state:
            start_iteration = state["last_iteration"] + 1
            latest_v, latest_prompt = PromptLoader.get_latest_version()
            if latest_prompt:
                current_prompt = latest_prompt
                logger.info(f"Resumed from iteration {start_iteration}, version {latest_v}")
    
    logger.info(f"Starting optimization from iteration {start_iteration}")
    logger.info(f"Goal: Achieve {STABILITY_THRESHOLD}+ score across all test cases")
    
    # Main optimization loop
    for iteration in range(start_iteration, start_iteration + max_iterations):
        logger.info(f"\n{'='*70}")
        logger.info(f"ITERATION {iteration}/{start_iteration + max_iterations - 1}")
        logger.info(f"{'='*70}\n")
        
        # Phase 1: RUN - Execute all test cases
        logger.info(f"Phase 1: Running {len(test_cases)} test cases...")
        test_results: List[TestResult] = []
        
        for i, test_case in enumerate(test_cases, 1):
            logger.info(f"  Test {i}/{len(test_cases)}: {test_case.id}")
            result = await execute_test_case(test_case, current_prompt, iteration)
            test_results.append(result)
            
            status = "✅ PASS" if result.passed else "❌ FAIL"
            logger.info(f"    {status} - Score: {result.score}/100")
        
        # Calculate metrics
        avg_score = sum(r.score for r in test_results) / len(test_results)
        passed_count = sum(1 for r in test_results if r.passed)
        token_count = len(current_prompt.split())
        
        logger.info(f"\nIteration {iteration} Results:")
        logger.info(f"  Average Score: {avg_score:.1f}/100")
        logger.info(f"  Tests Passed: {passed_count}/{len(test_results)}")
        logger.info(f"  Token Count: {token_count}")
        
        # Save detailed iteration log
        iteration_log_dir = session_log_dir / f"iteration_{iteration}"
        iteration_log_dir.mkdir(parents=True, exist_ok=True)
        
        # Save test results
        iteration_log = {
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "avg_score": avg_score,
            "passed_count": passed_count,
            "total_tests": len(test_results),
            "token_count": token_count,
            "test_results": [
                {
                    "test_case_id": r.test_case_id,
                    "score": r.score,
                    "passed": r.passed,
                    "duration_s": r.duration_s,
                    "vocab_count": r.vocab_count,
                    "dialogue_count": r.dialogue_count,
                    "issues": r.issues,
                    "validation": r.validation
                }
                for r in test_results
            ]
        }
        
        (iteration_log_dir / "results.json").write_text(
            json.dumps(iteration_log, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # Save prompt used in this iteration
        (iteration_log_dir / "prompt.txt").write_text(
            current_prompt,
            encoding="utf-8"
        )
        
        # Save each generated lesson as separate file
        lessons_dir = iteration_log_dir / "lessons"
        lessons_dir.mkdir(exist_ok=True)
        
        for r in test_results:
            if r.lesson_content:
                lesson_file = lessons_dir / f"{r.test_case_id}.json"
                lesson_file.write_text(
                    json.dumps(r.lesson_content, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
            # Save raw LLM response next to parsed lesson
            if getattr(r, "lesson_content_raw", None):
                raw_file = lessons_dir / f"{r.test_case_id}_raw.txt"
                try:
                    raw_file.write_text(r.lesson_content_raw, encoding="utf-8")
                except Exception:
                    raw_file.write_text(str(r.lesson_content_raw), encoding="utf-8")
        
        logger.info(f"  Iteration logs saved to: {iteration_log_dir}")
        logger.info(f"  Generated lessons saved to: {lessons_dir}")

        # Generate a simple session index.html for easy inspection
        try:
            index_path = session_log_dir / "index.html"
            html_lines = [
                "<html>",
                "<head><meta charset=\"utf-8\"><title>Optimizer Session Logs</title></head>",
                "<body>",
                f"<h1>Optimizer Session: {session_log_dir.name}</h1>",
                "<h2>Iterations</h2>",
                "<ul>"
            ]

            for it in sorted([p for p in session_log_dir.iterdir() if p.is_dir() and p.name.startswith('iteration_')]):
                html_lines.append(f"<li><b>{it.name}</b><ul>")
                # add results and prompt
                res_rel = it.name + "/results.json"
                prm_rel = it.name + "/prompt.txt"
                html_lines.append(f"<li><a href=\"{res_rel}\">results.json</a></li>")
                html_lines.append(f"<li><a href=\"{prm_rel}\">prompt.txt</a></li>")
                lessons_folder = it / "lessons"
                if lessons_folder.exists():
                    html_lines.append("<li>Lessons<ul>")
                    for lf in sorted(lessons_folder.iterdir()):
                        rel = it.name + "/lessons/" + lf.name
                        html_lines.append(f"<li><a href=\"{rel}\">{lf.name}</a></li>")
                    html_lines.append("</ul></li>")
                html_lines.append("</ul></li>")

            html_lines.append("</ul>")
            html_lines.append("</body></html>")

            index_path.write_text("\n".join(html_lines), encoding="utf-8")
            logger.info(f"  Session index written: {index_path}")
        except Exception as e:
            logger.warning(f"Failed to write session index.html: {e}")
        
        # Save this version
        filename = PromptLoader.save_version(iteration, current_prompt, avg_score)
        
        prompt_version = PromptVersion(
            version=iteration,
            timestamp=int(time.time()),
            prompt_text=current_prompt,
            token_count=token_count,
            avg_score=avg_score,
            test_results=test_results,
            filename=filename.name
        )
        prompt_versions.append(prompt_version)
        
        # Save state for resumption
        StateManager.save_state(iteration, prompt_versions)
        
        # Check if we've reached stability threshold
        if avg_score >= STABILITY_THRESHOLD and passed_count == len(test_results):
            logger.info(f"\n🎉 STABILITY THRESHOLD REACHED! 🎉")
            logger.info(f"Average score {avg_score:.1f} >= {STABILITY_THRESHOLD}")
            logger.info(f"All tests passed: {passed_count}/{len(test_results)}")
            break
        
        # Phase 2: ANALYZE - Categorize results
        failures = [r for r in test_results if r.score < 90]
        successes = [r for r in test_results if r.score >= 95]
        
        logger.info(f"\nPhase 2: Analysis")
        logger.info(f"  Failures (score < 90): {len(failures)}")
        logger.info(f"  Successes (score >= 95): {len(successes)}")
        
        # Stop if this is the last iteration
        if iteration >= start_iteration + max_iterations - 1:
            logger.info(f"\nMax iterations ({max_iterations}) reached.")
            break
        
        # Phase 3: REFINE - Generate improved prompt
        logger.info(f"\nPhase 3: Meta-Optimization (Gemini 2.5 Pro)")
        logger.info(f"  Analyzing failure patterns and generating improved prompt...")
        
        try:
            improved_prompt = await meta_refiner.refine_prompt(
                current_prompt,
                failures,
                successes,
                iteration
            )
            
            if improved_prompt and improved_prompt != current_prompt:
                current_prompt = improved_prompt
                logger.info(f"  ✅ Prompt refined successfully")
            else:
                logger.warning(f"  ⚠️ No improvement generated, keeping current prompt")
        
        except Exception as e:
            logger.error(f"  ❌ Refinement failed: {e}")
            logger.info(f"  Continuing with current prompt...")
    
    return prompt_versions


# ============================================================================
# LEGACY SIMPLE OPTIMIZER
# ============================================================================

async def optimize_system_prompt(iterations: int = 3) -> Dict[str, Any]:
    """Legacy simple optimizer - kept for backward compatibility"""
    settings = get_settings()
    provider = "stub" if not settings.gemini_api_key else (settings.default_provider_batch or "gemini")
    system_prompt = GENERATOR_PROMPT_COMPACT if settings.optimize_mode else GENERATOR_PROMPT
    
    if not system_prompt:
        system_prompt = "You are a helpful lesson planner. Return JSON as specified."
    
    logger.info(f"Starting simple optimization (provider: {provider})")
    
    runs: List[Dict[str, Any]] = []
    for i in range(iterations):
        logger.info(f"Run {i + 1}/{iterations}")
        # Simplified single pipeline run
        ctx = PipelineContext({
            "target_lang": "Spanish",
            "native_lang": "English",
            "cefr_level": "A2",
            "topic": "Optimization Test",
            "focus": "grammar",
        })
        steps = [LessonPlanner(), ContentCreator(), Validator()]
        orchestrator = PipelineOrchestrator(steps)
        start = time.time()
        try:
            await orchestrator.run(ctx)
        except Exception as e:
            logger.warning(f"Run {i + 1} failed: {e}")
        
        duration = time.time() - start
        validation = ctx.get("validation_result") or {}
        issues = validation.get("issues") if isinstance(validation, dict) else []
        
        runs.append({
            "run": i + 1,
            "duration_s": duration,
            "validation": validation,
            "validation_issues": issues or [],
        })
    
    # Aggregate and suggest improvement
    aggregated_issues = []
    for r in runs:
        for issue in r.get("validation_issues", []):
            if issue not in aggregated_issues:
                aggregated_issues.append(issue)
    
    improved_prompt = None
    try:
        llm_client = await get_llm_client()
        issues_text = json.dumps(aggregated_issues, ensure_ascii=False, indent=2) if aggregated_issues else "No validation issues detected"
        user_prompt = (
            "The current system prompt for lesson generation produced the following validation issues:\n"
            f"{issues_text}\n\n"
            "Propose an improved system prompt (single paragraph) to reduce these issues."
        )
        
        resp = await llm_client.generate(
            system_prompt="You are an expert prompt engineer for language-learning LLMs.",
            user_prompt=user_prompt,
            provider=provider,
            model=settings.gemini_model_batch,
            max_tokens=8000,
        )
        improved_prompt = resp.text.strip()
    except Exception as e:
        logger.warning(f"Failed to get improved prompt: {e}")
    
    record = {
        "timestamp": int(time.time()),
        "provider": provider,
        "system_prompt_used": system_prompt[:1000],
        "runs": runs,
        "aggregated_issues": aggregated_issues,
        "improved_prompt": improved_prompt,
    }
    
    # Save legacy format
    legacy_log = ROOT_DIR / "optimization_log_legacy.json"
    try:
        if legacy_log.exists():
            existing = json.loads(legacy_log.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = [existing]
        else:
            existing = []
        existing.append(record)
        legacy_log.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to write legacy log")
    
    return record


def main():
    """Run AOM - Auto-Optimizer Mode"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Auto-Optimizer Mode for ContentCreator Prompt")
    parser.add_argument("--iterations", type=int, default=5, help="Maximum optimization iterations")
    parser.add_argument("--resume", action="store_true", help="Resume from saved state")
    parser.add_argument("--legacy", action="store_true", help="Run legacy simple optimizer")
    parser.add_argument("--test-cases", type=str, default="test_cases.json", help="Path to test cases file")
    
    args = parser.parse_args()
    
    try:
        if args.legacy:
            logger.info("Running legacy simple optimizer...")
            res = asyncio.run(optimize_system_prompt(iterations=3))
            print("\nOptimization finished. Improved prompt:\n")
            print(res.get("improved_prompt") or "(no suggestion)")
        else:
            logger.info("Running Auto-Optimizer Mode (AOM)...")
            prompt_versions = asyncio.run(run_optimization(
                max_iterations=args.iterations,
                resume=args.resume,
                test_cases_file=args.test_cases
            ))
            
            # Generate final report
            report = ReportGenerator.generate(prompt_versions)
            OPT_REPORT_PATH.write_text(report, encoding="utf-8")
            
            logger.info(f"\n{'='*70}")
            logger.info(f"OPTIMIZATION COMPLETE")
            logger.info(f"{'='*70}\n")
            logger.info(f"Total iterations: {len(prompt_versions)}")
            
            if prompt_versions:
                best = max(prompt_versions, key=lambda v: v.avg_score)
                logger.info(f"Best score: {best.avg_score:.1f}/100 (Version {best.version})")
                logger.info(f"Report saved to: {OPT_REPORT_PATH}")
                logger.info(f"Prompts saved in: {PROMPTS_HISTORY_DIR}")
            
            print(f"\nSee full report: {OPT_REPORT_PATH}")
    
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
    except Exception as e:
        logger.exception(f"Optimization failed: {e}")
        raise

if __name__ == "__main__":
    main()

