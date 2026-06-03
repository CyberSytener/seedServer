"""
Optimizer V2 - Prompt + Validation Optimization

Расширенная версия оптимизатора, которая может оптимизировать:
1. Промпты (как V1)
2. Валидационные правила и веса
3. Комбинации промпт + валидация

Использует более сложные стратегии тестирования и анализа.
"""
from __future__ import annotations

import json
import logging
import time
from copy import deepcopy
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from .base import (
    BaseOptimizer,
    OptimizationTarget,
    OptimizerVersion,
    OptimizerTestCase,
    TestResult,
)
from .optimizer_v1 import ContentCreatorWithOverride, MetaRefiner
from ..pipeline.core import PipelineContext, PipelineOrchestrator
from ..pipeline.steps import LessonPlannerStep, LessonValidatorStep
from app.infrastructure.llm.client import get_llm_client
from ..lesson_engine import GENERATOR_PROMPT, GENERATOR_PROMPT_COMPACT
from ..settings import get_settings

logger = logging.getLogger(__name__)


# ============================================================================
# VALIDATION RULES STRUCTURE
# ============================================================================

DEFAULT_VALIDATION_RULES = {
    "exercise_count": {
        "min": 10,
        "max": 10,
        "weight": 15,
        "error_message": "Must have exactly 10 exercises"
    },
    "exercise_diversity": {
        "required_types": ["mcq", "translation", "word_bank", "listening_mimic"],
        "min_per_type": {
            "mcq": 3,
            "translation": 3,
            "word_bank": 2,
            "listening_mimic": 2
        },
        "weight": 20,
        "error_message": "Exercise diversity requirements not met"
    },
    "vocabulary_count": {
        "min": 8,
        "max": 15,
        "weight": 10,
        "error_message": "Vocabulary count out of range"
    },
    "dialogue_count": {
        "min": 2,
        "max": 5,
        "weight": 10,
        "error_message": "Dialogue count out of range"
    },
    "cefr_appropriateness": {
        "weight": 15,
        "error_message": "Content not appropriate for CEFR level"
    },
    "json_validity": {
        "weight": 30,
        "error_message": "Invalid JSON structure"
    }
}


# ============================================================================
# VALIDATOR WITH CUSTOM RULES
# ============================================================================

class ValidatorWithCustomRules(LessonValidatorStep):
    """Validator that uses custom validation rules"""
    
    def __init__(self, validation_rules: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.validation_rules = validation_rules or DEFAULT_VALIDATION_RULES
    
    async def execute(self, ctx: PipelineContext) -> None:
        """Execute validation with custom rules"""
        await self._emit_start(ctx, "Validating lesson (custom rules)...")
        
        content = ctx.get("lesson_content")
        if not content:
            await self._emit_error(ctx, "No lesson content to validate")
            ctx.set("validation_result", {
                "valid": False,
                "score": 0,
                "issues": ["No content found"],
                "recommendation": "REJECT"
            })
            return
        
        # Выполняем валидацию по кастомным правилам
        validation_result = self._validate_with_rules(content, ctx)
        ctx.set("validation_result", validation_result)
        
        score = validation_result.get("score", 0)
        recommendation = validation_result.get("recommendation", "REJECT")
        
        status = "✅ PASS" if recommendation == "APPROVE" else "⚠️ NEEDS WORK"
        await self._emit_complete(
            ctx,
            f"Validation complete: {status} (Score: {score}/100)",
            {"validation": validation_result}
        )
    
    def _validate_with_rules(
        self,
        content: Dict[str, Any],
        ctx: PipelineContext
    ) -> Dict[str, Any]:
        """Validate content using custom rules"""
        issues = []
        score = 0
        max_score = sum(rule.get("weight", 0) for rule in self.validation_rules.values())
        
        # JSON validity check
        if "json_validity" in self.validation_rules:
            rule = self.validation_rules["json_validity"]
            if isinstance(content, dict) and content.get("exercises"):
                score += rule["weight"]
            else:
                issues.append(rule["error_message"])
        
        # Exercise count check
        if "exercise_count" in self.validation_rules:
            rule = self.validation_rules["exercise_count"]
            exercises = content.get("exercises", [])
            count = len(exercises)
            
            if rule["min"] <= count <= rule["max"]:
                score += rule["weight"]
            else:
                issues.append(f"{rule['error_message']} (found {count})")
        
        # Exercise diversity check
        if "exercise_diversity" in self.validation_rules:
            rule = self.validation_rules["exercise_diversity"]
            exercises = content.get("exercises", [])
            
            type_counts = {}
            for ex in exercises:
                ex_type = ex.get("type", "unknown")
                type_counts[ex_type] = type_counts.get(ex_type, 0) + 1
            
            diversity_ok = True
            min_per_type = rule.get("min_per_type", {})
            
            for ex_type, min_count in min_per_type.items():
                if type_counts.get(ex_type, 0) < min_count:
                    diversity_ok = False
                    issues.append(f"Need at least {min_count} {ex_type} exercises (found {type_counts.get(ex_type, 0)})")
            
            if diversity_ok:
                score += rule["weight"]
        
        # Vocabulary count check
        if "vocabulary_count" in self.validation_rules:
            rule = self.validation_rules["vocabulary_count"]
            vocab = content.get("vocabulary", [])
            count = len(vocab)
            
            if rule["min"] <= count <= rule["max"]:
                score += rule["weight"]
            else:
                issues.append(f"{rule['error_message']} (found {count})")
        
        # Dialogue count check
        if "dialogue_count" in self.validation_rules:
            rule = self.validation_rules["dialogue_count"]
            dialogues = content.get("dialogues", [])
            count = len(dialogues)
            
            if rule["min"] <= count <= rule["max"]:
                score += rule["weight"]
            else:
                issues.append(f"{rule['error_message']} (found {count})")
        
        # CEFR appropriateness (simplified check)
        if "cefr_appropriateness" in self.validation_rules:
            rule = self.validation_rules["cefr_appropriateness"]
            expected_level = ctx.get("cefr_level", "A2")
            content_level = content.get("level", "")
            
            if content_level == expected_level:
                score += rule["weight"]
            else:
                issues.append(f"{rule['error_message']} (expected {expected_level}, got {content_level})")
        
        # Normalize score to 0-100
        normalized_score = int((score / max_score) * 100) if max_score > 0 else 0
        
        # Recommendation
        if normalized_score >= 95:
            recommendation = "APPROVE"
        elif normalized_score >= 80:
            recommendation = "REVISE"
        else:
            recommendation = "REJECT"
        
        return {
            "valid": len(issues) == 0,
            "score": normalized_score,
            "issues": issues,
            "recommendation": recommendation,
            "rule_scores": {
                "achieved": score,
                "max": max_score
            }
        }


# ============================================================================
# VALIDATION RULES REFINER
# ============================================================================

class ValidationRulesRefiner:
    """Uses LLM to optimize validation rules based on test results"""
    
    def __init__(self):
        self.settings = get_settings()
        # MULTI-MODEL PIPELINE: Use Gemini 2.5 Pro for validation rules optimization
        self.provider = "gemini" if self.settings.gemini_api_key else "stub"
        self.model = "gemini-2.5-pro"  # Advanced reasoning for validation optimization
    
    async def refine_rules(
        self,
        current_rules: Dict[str, Any],
        failures: List[TestResult],
        successes: List[TestResult],
        iteration: int
    ) -> Dict[str, Any]:
        """Refine validation rules based on test results"""
        llm_client = await get_llm_client()
        
        failure_analysis = self._analyze_failures(failures)
        success_analysis = self._analyze_successes(successes)
        
        meta_prompt = f"""You are an expert in language learning content validation.

**CURRENT VALIDATION RULES (Iteration {iteration}):**
```json
{json.dumps(current_rules, indent=2)}
```

**FAILURE ANALYSIS:**
{failure_analysis}

**SUCCESS ANALYSIS:**
{success_analysis}

**TASK:**
Analyze the validation rules and propose improvements that:
1. Reduce false positives (good content marked as bad)
2. Reduce false negatives (bad content marked as good)
3. Maintain pedagogical soundness
4. Keep total weights summing to 100

Return ONLY a valid JSON object with improved rules (same structure as input).
"""
        
        try:
            resp = await llm_client.generate(
                system_prompt="You are an expert in educational content validation.",
                user_prompt=meta_prompt,
                provider=self.provider,
                model=self.model,
                max_tokens=2000,
            )
            
            response_text = resp.text.strip()
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                improved_rules = json.loads(response_text[json_start:json_end])
                
                # Validate structure
                if self._validate_rules_structure(improved_rules):
                    return improved_rules
                else:
                    logger.warning("Improved rules have invalid structure, keeping current")
                    return current_rules
            else:
                logger.warning("No valid JSON in refinement response")
                return current_rules
        
        except Exception as e:
            logger.error(f"Rules refinement failed: {e}")
            return current_rules
    
    def _analyze_failures(self, failures: List[TestResult]) -> str:
        """Analyze failure patterns"""
        if not failures:
            return "No failures"
        
        # Group issues by type
        issue_counts = {}
        for result in failures:
            for issue in result.issues:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        
        analysis = f"Total failures: {len(failures)}\n\nCommon issues:\n"
        for issue, count in sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            analysis += f"- {issue}: {count} occurrences\n"
        
        return analysis
    
    def _analyze_successes(self, successes: List[TestResult]) -> str:
        """Analyze success patterns"""
        if not successes:
            return "No successes"
        
        avg_score = sum(r.score for r in successes) / len(successes)
        return f"Total successes: {len(successes)}\nAverage score: {avg_score:.1f}/100"
    
    def _validate_rules_structure(self, rules: Dict[str, Any]) -> bool:
        """Validate that rules have correct structure"""
        required_keys = ["exercise_count", "exercise_diversity", "json_validity"]
        
        for key in required_keys:
            if key not in rules:
                return False
            
            if "weight" not in rules[key]:
                return False
        
        return True


# ============================================================================
# OPTIMIZER V2 IMPLEMENTATION
# ============================================================================

class OptimizerV2(BaseOptimizer[Union[str, Dict[str, Any]]]):
    """
    Optimizer V2 - Prompt + Validation Optimization
    
    Может оптимизировать:
    - Только промпты (как V1)
    - Только валидацию
    - Промпты + валидацию одновременно
    """
    
    def __init__(
        self,
        target: OptimizationTarget,
        output_dir: Optional[Path] = None,
        stability_threshold: float = 95.0,
        max_iterations: int = 10,
        optimize_prompt: bool = True,
        optimize_validation: bool = True,
    ):
        if output_dir is None:
            output_dir = Path(__file__).parent.parent.parent / "optimizer_logs" / "v2"
        
        super().__init__(
            version=OptimizerVersion.V2_PROMPT_VALIDATION,
            target=target,
            output_dir=output_dir,
            stability_threshold=stability_threshold,
            max_iterations=max_iterations,
        )
        
        self.optimize_prompt = optimize_prompt
        self.optimize_validation = optimize_validation
        
        self.prompt_refiner = MetaRefiner() if optimize_prompt else None
        self.rules_refiner = ValidationRulesRefiner() if optimize_validation else None
        
        # Current artifacts
        self.current_prompt: Optional[str] = None
        self.current_rules: Optional[Dict[str, Any]] = None
    
    async def load_initial_artifact(self) -> Dict[str, Any]:
        """Load initial artifacts (prompt and/or rules)"""
        artifact = {}
        
        if self.optimize_prompt:
            settings = get_settings()
            prompt = GENERATOR_PROMPT_COMPACT if settings.optimize_mode else GENERATOR_PROMPT
            if not prompt:
                prompt = "You are a language learning content creator."
            
            artifact["prompt"] = prompt
            self.current_prompt = prompt
            logger.info(f"Loaded initial prompt ({len(prompt.split())} tokens)")
        
        if self.optimize_validation:
            rules = deepcopy(DEFAULT_VALIDATION_RULES)
            artifact["validation_rules"] = rules
            self.current_rules = rules
            logger.info(f"Loaded initial validation rules ({len(rules)} rules)")
        
        return artifact
    
    async def execute_test_case(
        self,
        test_case: OptimizerTestCase,
        artifact: Dict[str, Any],
        iteration: int
    ) -> TestResult:
        """Execute test case with current prompt and/or validation rules"""
        ctx = PipelineContext({
            "target_lang": test_case.target_lang,
            "native_lang": test_case.native_lang,
            "cefr_level": test_case.cefr_level,
            "topic": test_case.topic,
            "focus": test_case.focus,
            "prompt_version": iteration,
        })
        
        # Build pipeline steps
        steps = [LessonPlannerStep()]
        
        # Add content creator with optional custom prompt
        if self.optimize_prompt and "prompt" in artifact:
            steps.append(ContentCreatorWithOverride(override_prompt=artifact["prompt"]))
        else:
            from ..pipeline.steps import LessonContentStep
            steps.append(LessonContentStep())
        
        # Add validator with optional custom rules
        if self.optimize_validation and "validation_rules" in artifact:
            steps.append(ValidatorWithCustomRules(validation_rules=artifact["validation_rules"]))
        else:
            steps.append(LessonValidatorStep())
        
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
                "optimized_prompt": self.optimize_prompt,
                "optimized_validation": self.optimize_validation,
            }
        )
    
    async def refine_artifact(
        self,
        current_artifact: Dict[str, Any],
        failures: List[TestResult],
        successes: List[TestResult],
        iteration: int
    ) -> Dict[str, Any]:
        """Refine prompt and/or validation rules"""
        improved_artifact = deepcopy(current_artifact)
        
        # Refine prompt if enabled
        if self.optimize_prompt and "prompt" in current_artifact and self.prompt_refiner:
            logger.info("  Refining prompt...")
            improved_prompt = await self.prompt_refiner.refine_prompt(
                current_artifact["prompt"],
                failures,
                successes,
                iteration,
                token_limit=1500
            )
            
            if improved_prompt != current_artifact["prompt"]:
                improved_artifact["prompt"] = improved_prompt
                self.current_prompt = improved_prompt
                logger.info("  ✅ Prompt refined")
            else:
                logger.info("  ⚠️ Prompt unchanged")
        
        # Refine validation rules if enabled
        if self.optimize_validation and "validation_rules" in current_artifact and self.rules_refiner:
            logger.info("  Refining validation rules...")
            improved_rules = await self.rules_refiner.refine_rules(
                current_artifact["validation_rules"],
                failures,
                successes,
                iteration
            )
            
            if improved_rules != current_artifact["validation_rules"]:
                improved_artifact["validation_rules"] = improved_rules
                self.current_rules = improved_rules
                logger.info("  ✅ Validation rules refined")
            else:
                logger.info("  ⚠️ Validation rules unchanged")
        
        return improved_artifact
    
    def save_artifact(
        self,
        artifact: Dict[str, Any],
        iteration: int,
        avg_score: float
    ) -> Path:
        """Save artifacts (prompt and/or rules)"""
        artifacts_dir = self.session_dir / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        
        iteration_dir = artifacts_dir / f"iteration_{iteration}"
        iteration_dir.mkdir(exist_ok=True)
        
        # Save prompt if present
        if "prompt" in artifact:
            prompt_file = iteration_dir / f"prompt_{int(avg_score)}.txt"
            prompt_file.write_text(artifact["prompt"], encoding="utf-8")
            logger.info(f"  Saved prompt: {prompt_file.name}")
        
        # Save validation rules if present
        if "validation_rules" in artifact:
            rules_file = iteration_dir / f"validation_rules_{int(avg_score)}.json"
            rules_file.write_text(
                json.dumps(artifact["validation_rules"], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            logger.info(f"  Saved validation rules: {rules_file.name}")
        
        # Save combined artifact
        combined_file = iteration_dir / f"artifact_{int(avg_score)}.json"
        combined_file.write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        return iteration_dir
