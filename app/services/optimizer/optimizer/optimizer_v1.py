"""
Optimizer V1 - Prompt-Only Optimization

Первая версия оптимизатора, фокусируется только на оптимизации промптов
для ContentCreator. Это рефакторинг оригинального optimizer_mode.py
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List, Optional

from .base import (
    BaseOptimizer,
    OptimizationTarget,
    OptimizerVersion,
    OptimizerTestCase,
    TestResult,
)
from ..pipeline.core import PipelineContext, PipelineOrchestrator
from ..pipeline.steps import LessonPlannerStep, LessonContentStep, LessonValidatorStep
from app.infrastructure.llm.client import get_llm_client
from ..lesson_engine import GENERATOR_PROMPT, GENERATOR_PROMPT_COMPACT
from ..settings import get_settings

logger = logging.getLogger(__name__)


# ============================================================================
# CONTENT CREATOR WITH PROMPT OVERRIDE
# ============================================================================

class ContentCreatorWithOverride(LessonContentStep):
    """ContentCreator that accepts a custom system prompt"""
    
    def __init__(self, override_prompt: Optional[str] = None):
        super().__init__()
        self.override_prompt = override_prompt
    
    async def execute(self, ctx: PipelineContext) -> None:
        """Execute with optional prompt override"""
        if self.override_prompt:
            await self._emit_start(ctx, "Crafting lesson content (custom prompt)...")
            
            plan = ctx.get("lesson_plan")
            if not plan:
                await self._emit_error(ctx, "No lesson plan found")
                raise ValueError("No lesson plan found")
            
            target_lang = ctx.get("target_lang", "Spanish")
            native_lang = ctx.get("native_lang", "English")
            cefr_level = ctx.get("cefr_level", "A2")
            
            task_descriptions = plan.get("task_descriptions", [])
            if not task_descriptions:
                task_descriptions = [
                    "Task 1: [MCQ] Vocabulary recognition - core words",
                    "Task 2: [MCQ] Vocabulary recognition - context-based",
                    "Task 3: [MCQ] Vocabulary recognition - advanced synonyms",
                    "Task 4: [Translation] Basic phrase translation",
                    "Task 5: [Translation] Dialogue line translation",
                    "Task 6: [Translation] Complex sentence translation",
                    "Task 7: [Word Bank] Sentence construction",
                    "Task 8: [Word Bank] Grammar application",
                    "Task 9: [Listening Mimic] Pronunciation practice",
                    "Task 10: [Listening Mimic] Dialogue exchange"
                ]
            
            user_prompt = f"""Based on this lesson plan:
{json.dumps(plan, indent=2)}

Create lesson content for {target_lang} learners (CEFR {cefr_level}).

MANDATORY EXERCISE DIVERSITY:
- Tasks 1-3: Multiple Choice (MCQ)
- Tasks 4-6: Translation
- Tasks 7-8: Word Bank
- Tasks 9-10: Listening Mimic

Task Guidance:
{chr(10).join(task_descriptions)}

Return ONLY valid JSON:
{{
  "lessonId": "unique_id",
  "mode": "comprehensive",
  "targetLang": "{target_lang}",
  "nativeLang": "{native_lang}",
  "level": "{cefr_level}",
  "title": "{plan.get('lessonTitle', 'Untitled')}",
  "exercises": [{{exercise_1}}, ..., {{exercise_10}}]
}}"""
            
            settings = get_settings()
            llm_client = await get_llm_client()
            
            # MULTI-MODEL PIPELINE: Use Gemini 2.0 Flash for content generation
            provider = "gemini" if settings.gemini_api_key else "stub"
            model = "gemini-2.0-flash-exp"  # Fast content generator
            
            try:
                llm_resp = await llm_client.generate(
                    system_prompt=self.override_prompt,
                    user_prompt=user_prompt,
                    provider=provider,
                    model=model,
                    max_tokens=8000
                )
                
                response_text = llm_resp.text
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                
                if json_start >= 0 and json_end > json_start:
                    content = json.loads(response_text[json_start:json_end])
                    ctx.set("lesson_content", content)
                    ctx.set("lesson_content_raw", response_text)
                    
                    exercise_count = len(content.get("exercises", []))
                    await self._emit_complete(
                        ctx,
                        f"Content created: {exercise_count} exercises",
                        {"exercise_count": exercise_count}
                    )
                else:
                    await self._emit_error(ctx, "No valid JSON in response")
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
    """Uses LLM to refine prompts based on test results"""
    
    def __init__(self):
        self.settings = get_settings()
        # MULTI-MODEL PIPELINE: Use Gemini 2.5 Pro for meta-analysis and optimization
        self.provider = "gemini" if self.settings.gemini_api_key else "stub"
        self.model = "gemini-2.5-pro"  # Advanced reasoning for prompt optimization
    
    async def refine_prompt(
        self,
        current_prompt: str,
        failures: List[TestResult],
        successes: List[TestResult],
        iteration: int,
        token_limit: int = 1500
    ) -> str:
        """Refine prompt based on test results"""
        llm_client = await get_llm_client()
        
        failure_summary = self._build_failure_summary(failures)
        success_summary = self._build_success_summary(successes)
        
        meta_prompt = f"""You are an expert prompt engineer for language learning content.

**CURRENT PROMPT (Iteration {iteration}):**
```
{current_prompt[:800]}...
```

**PERFORMANCE:**
Failures (Score < 90): {len(failures)}
{failure_summary}

Successes (Score >= 95): {len(successes)}
{success_summary}

**TASK:**
Analyze failures and produce an improved system prompt that:
1. Retains successful patterns
2. Fixes failure patterns
3. Is under {token_limit} tokens
4. Is pedagogically sound

Return ONLY the improved prompt text (no markdown, no commentary)."""
        
        try:
            resp = await llm_client.generate(
                system_prompt="You are an expert prompt engineer.",
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
            if token_count > token_limit:
                words = improved.split()[:token_limit]
                improved = " ".join(words) + "..."
                logger.warning(f"Truncated prompt from {token_count} to {token_limit} tokens")
            
            return improved
        
        except Exception as e:
            logger.error(f"Meta-refinement failed: {e}")
            return current_prompt
    
    def _build_failure_summary(self, failures: List[TestResult]) -> str:
        """Build failure summary"""
        if not failures:
            return "None"
        
        parts = []
        for r in failures[:3]:
            parts.append(
                f"- {r.test_case_id}: Score {r.score}/100\n"
                f"  Issues: {', '.join(r.issues) if r.issues else 'None'}"
            )
        
        return "\n".join(parts)
    
    def _build_success_summary(self, successes: List[TestResult]) -> str:
        """Build success summary"""
        if not successes:
            return "None"
        
        avg_score = sum(r.score for r in successes) / len(successes)
        return f"Average: {avg_score:.1f}/100 across {len(successes)} cases"


# ============================================================================
# OPTIMIZER V1 IMPLEMENTATION
# ============================================================================

class OptimizerV1(BaseOptimizer[str]):
    """
    Optimizer V1 - Prompt-Only Optimization
    
    Оптимизирует промпт для ContentCreator используя итеративное
    тестирование и LLM-based рефайнмент.
    """
    
    def __init__(
        self,
        target: OptimizationTarget = OptimizationTarget.PROMPT_CONTENT_CREATOR,
        output_dir: Optional[Path] = None,
        stability_threshold: float = 95.0,
        max_iterations: int = 10,
        token_limit: int = 1500,
    ):
        if output_dir is None:
            output_dir = Path(__file__).parent.parent.parent / "optimizer_logs" / "v1"
        
        super().__init__(
            version=OptimizerVersion.V1_PROMPT_ONLY,
            target=target,
            output_dir=output_dir,
            stability_threshold=stability_threshold,
            max_iterations=max_iterations,
        )
        
        self.token_limit = token_limit
        self.meta_refiner = MetaRefiner()
    
    async def load_initial_artifact(self) -> str:
        """Load initial prompt"""
        settings = get_settings()
        prompt = GENERATOR_PROMPT_COMPACT if settings.optimize_mode else GENERATOR_PROMPT
        
        if not prompt:
            prompt = "You are a language learning content creator. Generate lessons as JSON."
        
        logger.info(f"Loaded initial prompt ({len(prompt.split())} tokens)")
        return prompt
    
    async def execute_test_case(
        self,
        test_case: OptimizerTestCase,
        artifact: str,  # prompt
        iteration: int
    ) -> TestResult:
        """Execute single test case"""
        ctx = PipelineContext({
            "target_lang": test_case.target_lang,
            "native_lang": test_case.native_lang,
            "cefr_level": test_case.cefr_level,
            "topic": test_case.topic,
            "focus": test_case.focus,
            "prompt_version": iteration,
        })
        
        steps = [
            LessonPlannerStep(),
            ContentCreatorWithOverride(override_prompt=artifact),
            LessonValidatorStep()
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
        
        score = validation.get("score", 0) if isinstance(validation, dict) else 0
        issues = validation.get("issues", []) if isinstance(validation, dict) else []
        
        passed = (score >= test_case.min_score and len(issues) == 0)
        
        return TestResult(
            test_case_id=test_case.id,
            duration_s=duration,
            score=score,
            passed=passed,
            issues=issues,
            validation_details=validation if isinstance(validation, dict) else {},
            metadata={
                "vocab_count": len(content.get("vocabulary", [])) if isinstance(content, dict) else 0,
                "dialogue_count": len(content.get("dialogues", [])) if isinstance(content, dict) else 0,
                "exercise_count": len(content.get("exercises", [])) if isinstance(content, dict) else 0,
            }
        )
    
    async def refine_artifact(
        self,
        current_artifact: str,
        failures: List[TestResult],
        successes: List[TestResult],
        iteration: int
    ) -> str:
        """Refine prompt using meta-refiner"""
        return await self.meta_refiner.refine_prompt(
            current_artifact,
            failures,
            successes,
            iteration,
            self.token_limit
        )
    
    def save_artifact(self, artifact: str, iteration: int, avg_score: float) -> Path:
        """Save prompt to file"""
        # Создаем директорию для промптов
        prompts_dir = self.session_dir / "prompts"
        prompts_dir.mkdir(exist_ok=True)
        
        filename = f"prompt_v{iteration}_{int(avg_score)}.txt"
        filepath = prompts_dir / filename
        
        filepath.write_text(artifact, encoding="utf-8")
        logger.info(f"  Saved prompt: {filename}")
        
        return filepath
