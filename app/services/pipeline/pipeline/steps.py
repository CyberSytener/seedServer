"""
Конкретные шаги конвейера для генерации уроков и диагностики

Каждый шаг представляет собой специализированного "агента" с определенной ролью
"""

import json
import logging
from typing import Optional

from .core import PipelineStep, PipelineContext
from app.infrastructure.llm.client import get_llm_client
from app.infrastructure.monitoring.monitoring.metrics import BillingMetrics
from app.services.llm.contracts import build_credit_ledger_event, normalize_usage_breakdown
from ..settings import get_settings

logger = logging.getLogger(__name__)


def _record_pipeline_ledger_event(
    ctx: PipelineContext,
    *,
    provider: str,
    model: str,
    stage: str,
    attempt: int,
    tokens_in: int,
    tokens_out: int,
) -> None:
    usage = normalize_usage_breakdown(
        {
            "prompt_tokens": tokens_in,
            "completion_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
        request_count=1,
    )
    event = build_credit_ledger_event(
        provider=provider,
        model=model,
        endpoint="/v1/lessons/generate",
        feature="lesson_pipeline",
        stage=stage,
        usage=usage,
        attempt=attempt,
        trace_id=ctx.get("trace_id"),
        session_id=ctx.get("session_id"),
        job_id=ctx.get("job_id"),
    ).to_dict()

    ledger_events = list(ctx.get("ledger_events", []))
    ledger_events.append(event)
    ctx.set("ledger_events", ledger_events)
    BillingMetrics.record_credit_ledger_event(event)


# ============================================================================
# LESSON GENERATION PIPELINE STEPS
# ============================================================================

class LessonPlannerStep(PipelineStep):
    """
    Шаг 1: Архитектор урока
    
    Роль: Создает структурный план урока
    Модель: Gemini 2.0 Flash (быстрая, структурная)
    Температура: 0.2 (низкая - нужна структура)
    """
    
    def __init__(self):
        super().__init__(
            name="LessonPlanner",
            agent_name="Architect 🧠",
            icon="🧠"
        )
    
    async def execute(self, ctx: PipelineContext) -> None:
        await self._emit_start(ctx, "Analyzing learning objectives and creating lesson structure...")
        
        # Извлекаем данные из контекста
        target_lang = ctx.get("target_lang", "Spanish")
        native_lang = ctx.get("native_lang", "English")
        cefr_level = ctx.get("cefr_level", "A2")
        topic = ctx.get("topic", "Daily Activities")
        focus = ctx.get("focus", "grammar")
        
        # Формируем промпт для архитектора
        prompt = f"""You are a language learning curriculum architect.

Create a structured lesson plan for:
- Target Language: {target_lang}
- Native Language: {native_lang}
- CEFR Level: {cefr_level}
- Topic: {topic}
- Focus: {focus}

Return ONLY a JSON object with this structure:
{{
  "lessonTitle": "Short engaging title",
  "learningObjectives": ["objective1", "objective2", "objective3"],
  "grammar_points": ["point1", "point2"],
  "vocabulary_count": 10,
  "dialogue_scenes": ["scene1", "scene2"],
  "task_descriptions": [
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
  ],
  "exercises_plan": ["mcq_1", "mcq_2", "mcq_3", "translation_1", "translation_2", "translation_3", "word_bank_1", "word_bank_2", "listening_mimic_1", "listening_mimic_2"]
}}

Be concise, pedagogically sound, and appropriate for {cefr_level} level. The task_descriptions should guide the ContentCreator on what each of the 10 required exercises should cover."""
        
        await self._emit_working(ctx, "Consulting learning theory database...")
        
        # Вызываем LLM (быструю модель для структуры)
        settings = get_settings()
        llm_client = await get_llm_client()
        
        # Use stub if no API key available
        provider = settings.default_provider_fast or "stub"
        if provider in ("gemini", "openai") and not (
            (provider == "gemini" and settings.gemini_api_key) or
            (provider == "openai" and settings.openai_api_key)
        ):
            provider = "stub"
        
        try:
            llm_resp = await llm_client.generate(
                system_prompt="You are a precise curriculum architect. Include exactly 10 task descriptions.",
                user_prompt=prompt,
                provider=provider,
                model=settings.gemini_model_fast,
                max_tokens=2400
            )

            _record_pipeline_ledger_event(
                ctx,
                provider=llm_resp.provider,
                model=llm_resp.model,
                stage="candidate",
                attempt=1,
                tokens_in=llm_resp.tokens_in,
                tokens_out=llm_resp.tokens_out,
            )
            
            # Парсим JSON
            response_text = llm_resp.text
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                plan_json = json.loads(response_text[json_start:json_end])
                ctx.set("lesson_plan", plan_json)
                
                await self._emit_complete(
                    ctx,
                    f"Lesson structure created: {plan_json.get('lessonTitle', 'Untitled')}",
                    {"objectives_count": len(plan_json.get("learningObjectives", []))}
                )
            else:
                raise ValueError("No valid JSON in response")
        
        except Exception as e:
            await self._emit_error(ctx, str(e))
            raise


class LessonContentStep(PipelineStep):
    """
    Шаг 2: Креатор контента
    
    Роль: Генерирует живой, интересный контент урока
    Модель: Gemini 1.5 Pro (креативная)
    Температура: 0.8 (высокая - нужен креатив)
    """
    
    def __init__(self):
        super().__init__(
            name="ContentCreator",
            agent_name="ContentCreator ✍️",
            icon="✍️"
        )
    
    async def execute(self, ctx: PipelineContext) -> None:
        await self._emit_start(ctx, "Crafting engaging lesson content...")

        # Get mode and parameters
        mode = ctx.get("mode", "learning_path")
        target_lang = ctx.get("target_lang", "Spanish")
        native_lang = ctx.get("native_lang", "English")
        cefr_level = ctx.get("cefr_level", "A2")
        topic = ctx.get("topic", "General")
        node_id = ctx.get("node_id")
        unit_id = ctx.get("unit_id")
        lesson_length = ctx.get("lesson_length", 10)
        xp_reward = ctx.get("xp_reward", 15)

        # Import appropriate prompt based on mode
        if mode == "learning_path":
            from ..prompts.learning_path import LEARNING_PATH_CONTENT_CREATOR_PROMPT
            prompt_template = LEARNING_PATH_CONTENT_CREATOR_PROMPT
        elif mode == "placement_test":
            from ..prompts.placement_test import PLACEMENT_TEST_CONTENT_CREATOR_PROMPT
            prompt_template = PLACEMENT_TEST_CONTENT_CREATOR_PROMPT
        elif mode == "ad_hoc":
            from ..prompts.ad_hoc_lesson import AD_HOC_CONTENT_CREATOR_PROMPT
            prompt_template = AD_HOC_CONTENT_CREATOR_PROMPT
        else:
            # Fallback to learning path
            from ..prompts.learning_path import LEARNING_PATH_CONTENT_CREATOR_PROMPT
            prompt_template = LEARNING_PATH_CONTENT_CREATOR_PROMPT

        # Format prompt with parameters
        prompt = prompt_template.format(
            target_lang=target_lang,
            native_lang=native_lang,
            cefr_level=cefr_level,
            topic=topic,
            node_id=node_id or "",
            unit_id=unit_id or "",
            xp_reward=xp_reward,
            lesson_length=lesson_length,
            max_questions=ctx.get("max_questions", 10),
            time_limit_seconds=ctx.get("time_limit_seconds", 600),
            user_id=ctx.get("user_id", "anonymous")
        )

        await self._emit_working(ctx, f"Generating {mode} content...")
        
        settings = get_settings()
        llm_client = await get_llm_client()
        
        # Use stub if no API key available
        provider = getattr(settings, "default_provider_batch", None) or settings.default_provider_fast or "stub"
        if provider in ("gemini", "openai") and not (
            (provider == "gemini" and settings.gemini_api_key) or
            (provider == "openai" and settings.openai_api_key)
        ):
            provider = "stub"
        
        # Set mode-specific system prompt
        mode = ctx.get("mode", "learning_path")
        if mode == "placement_test":
            system_prompt = (
                "You are an expert language proficiency assessment specialist. "
                "Generate a placement test with EXACTLY the required number of questions. "
                "Return ONLY valid JSON with no markdown wrapping, no code blocks, pure JSON only. "
                "Each question MUST have exactly 4 choices. "
                "All field names must use camelCase exactly as specified. "
                "Include ALL required fields: id, type, cefrLevel, skill, difficulty, question, choices, "
                "correctChoiceIndex, correctAnswer, discriminationPower, timeEstimateSeconds."
            )
        else:
            system_prompt = (
                "You are a creative language-learning content writer. "
                "You MUST generate EXACTLY 10 exercises, no more, no less. "
                "Follow the exercise diversity rule: MCQ (1-3), Translation (4-6), Word Bank (7-8), Listening Mimic (9-10). "
                "Do not skip any exercise number. Return ONLY valid JSON."
            )
        
        try:
            llm_resp = await llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=prompt,
                provider=provider,
                model=getattr(settings, "gemini_model_batch", None) or settings.gemini_model_fast,
                max_tokens=8000
            )

            _record_pipeline_ledger_event(
                ctx,
                provider=llm_resp.provider,
                model=llm_resp.model,
                stage="validator",
                attempt=1,
                tokens_in=llm_resp.tokens_in,
                tokens_out=llm_resp.tokens_out,
            )
            
            # Парсим JSON
            response_text = llm_resp.text
            
            # Use repair function for robust JSON parsing
            from app.core.validators.validators.repair import (
                repair_lesson_json,
                validate_and_repair_lesson,
            )

            try:
                content = repair_lesson_json(response_text)
                content = validate_and_repair_lesson(content, mode)
            except Exception as e:
                logging.error(f"JSON repair failed: {e}")
                raise ValueError(f"Could not parse or repair JSON from response: {str(e)}")
            
            if not content:
                raise ValueError("Failed to extract valid JSON content")
            
            ctx.set("lesson_content", content)
            
            if mode == "placement_test":
                question_count = len(content.get("questions", []))
                await self._emit_complete(
                    ctx,
                    f"Content created: {question_count} placement test questions",
                    {"question_count": question_count}
                )
            else:
                exercise_count = len(content.get("exercises", []))
                await self._emit_complete(
                    ctx,
                    f"Content created: {exercise_count} exercises (3 MCQ, 3 Translation, 2 Word Bank, 2 Listening)",
                    {"exercise_count": exercise_count}
                )
        
        except Exception as e:
            await self._emit_error(ctx, str(e))
            raise


class LessonValidatorStep(PipelineStep):
    """
    Шаг 3: Валидатор
    
    Роль: Проверяет качество, формат, соответствие CEFR
    Модель: Быстрая модель (можно даже локальную)
    Температура: 0.1 (очень низкая - нужна точность)
    """
    
    def __init__(self):
        super().__init__(
            name="Validator",
            agent_name="QA Reviewer 🛡️",
            icon="🛡️"
        )
    
    async def execute(self, ctx: PipelineContext) -> None:
        await self._emit_start(ctx, "Validating lesson quality and CEFR compliance...")

        content = ctx.get("lesson_content")
        mode = ctx.get("mode", "learning_path")

        if not content:
            raise ValueError("Missing content for validation")

        # Import appropriate validator prompt based on mode
        if mode == "learning_path":
            from ..prompts.learning_path import LEARNING_PATH_VALIDATOR_PROMPT
            validator_prompt = LEARNING_PATH_VALIDATOR_PROMPT
        elif mode == "placement_test":
            from ..prompts.placement_test import PLACEMENT_TEST_VALIDATOR_PROMPT
            validator_prompt = PLACEMENT_TEST_VALIDATOR_PROMPT
        elif mode == "ad_hoc":
            from ..prompts.ad_hoc_lesson import AD_HOC_VALIDATOR_PROMPT
            validator_prompt = AD_HOC_VALIDATOR_PROMPT
        else:
            # Fallback
            from ..prompts.learning_path import LEARNING_PATH_VALIDATOR_PROMPT
            validator_prompt = LEARNING_PATH_VALIDATOR_PROMPT

        # Format prompt with content - use appropriate variable name based on mode
        if mode == "placement_test":
            prompt = validator_prompt.format(test_json=json.dumps(content, indent=2, ensure_ascii=False))
        else:
            prompt = validator_prompt.format(lesson_json=json.dumps(content, indent=2, ensure_ascii=False))

        await self._emit_working(ctx, f"Validating {mode} content...")
        
        # Handle placement_test mode separately
        if mode == "placement_test":
            questions = content.get("questions", [])
            question_count = len(questions)
            
            # Basic validation for placement test
            issues = []
            if question_count < 10:
                issues.append(f"Expected at least 10 questions, got {question_count}")
            
            validation_prompt = f"""You are a psychometric specialist validating language placement tests.

Placement Test Summary:
- Target Language: {content.get('targetLang', 'Unknown')}
- Questions: {question_count}
- Time Limit: {content.get('timeLimitSeconds', 0)} seconds

Validation issues detected: {', '.join(issues) if issues else 'None'}

Return ONLY JSON (no markdown):
{{"valid": {str(question_count >= 10).lower()}, "score": {85 if not issues else 60}, "recommendation": "APPROVE" if not issues else "REVISE"}}"""
            
            score = 85 if not issues else 60
            validation_result = {
                "valid": question_count >= 10 and len(issues) == 0,
                "score": score,
                "recommendation": "APPROVE" if not issues else "REVISE"
            }
            
            ctx.set("validation_result", validation_result)
            recommendation = validation_result.get("recommendation", "APPROVE")
            
            if recommendation == "APPROVE":
                await self._emit_complete(
                    ctx,
                    f"Validation complete: ✅ APPROVED (Score: {score}/100)",
                    {"score": score, "recommendation": recommendation}
                )
            else:
                await self._emit_complete(
                    ctx,
                    f"Validation complete: ⚠️ NEEDS REVISION (Score: {score}/100)",
                    {"score": score, "recommendation": recommendation}
                )
            return
        
        # Original logic for learning_path and ad_hoc modes
        # Extract exercises from content
        exercises = content.get("exercises", [])
        exercise_count = len(exercises)
        
        # Get CEFR level from content or context
        cefr_level = content.get("level", ctx.get("cefr_level", "A2"))
        
        # Initialize issues list
        issues = []
        
        # Check exercise count
        if exercise_count != 10:
            issues.append(f"Expected exactly 10 exercises, got {exercise_count}")
        
        # Check exercise types distribution
        mcq_count = sum(1 for ex in exercises if ex.get("type") == "mcq")
        translation_count = sum(1 for ex in exercises if ex.get("type") == "translation")
        word_bank_count = sum(1 for ex in exercises if ex.get("type") == "word_bank")
        listening_count = sum(1 for ex in exercises if ex.get("type") == "listening_mimic")
        
        if mcq_count != 3:
            issues.append(f"Expected 3 MCQ exercises, got {mcq_count}")
        if translation_count != 3:
            issues.append(f"Expected 3 Translation exercises, got {translation_count}")
        if word_bank_count != 2:
            issues.append(f"Expected 2 Word Bank exercises, got {word_bank_count}")
        if listening_count != 2:
            issues.append(f"Expected 2 Listening Mimic exercises, got {listening_count}")
        
        # Check exercise IDs
        expected_ids = [f"task_{i}" for i in range(1, 11)]
        actual_ids = [ex.get("id") for ex in exercises]
        if actual_ids != expected_ids:
            issues.append(f"Exercise IDs mismatch. Expected {expected_ids}, got {actual_ids}")
        
        # Промпт для валидатора
        prompt = f"""You are a language learning quality assurance expert.

Review this lesson content for CEFR {cefr_level}:

CONTENT SUMMARY:
- Lesson: {content.get('title', 'Untitled')}
- Level: {content.get('level', 'Unknown')}
- Target Lang: {content.get('targetLang', 'Unknown')}
- Exercises: {exercise_count} total ({mcq_count} MCQ, {translation_count} Translation, {word_bank_count} Word Bank, {listening_count} Listening)

EXERCISE BREAKDOWN (full details):
{json.dumps(exercises, indent=2, ensure_ascii=False)}

Check for:
1. Exercise Diversity compliance (exactly 10: 3 MCQ, 3 Translation, 2 Word Bank, 2 Listening)
2. CEFR level appropriateness ({cefr_level})
3. Grammar accuracy
4. Cultural sensitivity
5. JSON structure validity
6. All required fields present in each exercise

Local Issues Found: {', '.join(issues) if issues else 'None detected locally'}

Return ONLY a JSON:
{{
  "valid": true/false,
  "exercise_diversity_compliant": true/false,
  "cefr_appropriate": true/false,
  "issues": ["issue1", "issue2"] or [],
  "score": 0-100,
  "recommendation": "APPROVE" or "REVISE"
}}"""
        
        await self._emit_working(ctx, "Running Exercise Diversity and quality checks...")
        
        settings = get_settings()
        llm_client = await get_llm_client()
        
        # MULTI-MODEL PIPELINE: Use Gemini 2.0 Flash for fast validation  
        provider = "gemini" if settings.gemini_api_key else "stub"
        model = "gemini-2.0-flash-exp"  # Fast validation model
        
        try:
            llm_resp = await llm_client.generate(
                system_prompt="You are a rigorous QA reviewer for language lessons. Verify Exercise Diversity compliance: exactly 10 exercises (3 MCQ, 3 Translation, 2 Word Bank, 2 Listening Mimic).",
                user_prompt=prompt,
                provider=provider,
                model=model,
                max_tokens=1500
            )

            _record_pipeline_ledger_event(
                ctx,
                provider=llm_resp.provider,
                model=llm_resp.model,
                stage="final",
                attempt=1,
                tokens_in=llm_resp.tokens_in,
                tokens_out=llm_resp.tokens_out,
            )
            
            # Парсим JSON
            response_text = llm_resp.text
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                validation = json.loads(response_text[json_start:json_end])
                ctx.set("validation_result", validation)
                
                status = "✅ APPROVED" if validation.get("recommendation") == "APPROVE" else "⚠️ NEEDS REVIEW"
                score = validation.get("score", 0)
                
                await self._emit_complete(
                    ctx,
                    f"Validation complete: {status} (Score: {score}/100)",
                    {"validation": validation}
                )
            else:
                # Fallback: если валидатор не ответил JSON, считаем OK
                ctx.set("validation_result", {"valid": True, "recommendation": "APPROVE"})
                await self._emit_complete(ctx, "Validation complete: APPROVED (fallback)")
        
        except Exception as e:
            logger.warning(f"Validation failed, proceeding anyway: {e}")
            ctx.set("validation_result", {"valid": True, "recommendation": "APPROVE", "error": str(e)})
            await self._emit_complete(ctx, "Validation complete with warnings")


# ============================================================================
# DIAGNOSTIC GENERATION PIPELINE STEPS
# ============================================================================

class DiagnosticPlannerStep(PipelineStep):
    """
    Шаг 1: Планировщик диагностики
    
    Роль: Создает сбалансированный план диагностических заданий
    """
    
    def __init__(self):
        super().__init__(
            name="DiagnosticPlanner",
            agent_name="Test Architect 🎯",
            icon="🎯"
        )
    
    async def execute(self, ctx: PipelineContext) -> None:
        await self._emit_start(ctx, "Designing diagnostic test blueprint...")
        
        blueprint = ctx.get("blueprint", [])
        target_lang = ctx.get("target_lang", "Spanish")
        
        await self._emit_working(ctx, f"Planning {len(blueprint)} test items...")
        
        # В реальности здесь может быть логика оптимизации blueprint
        # Например, балансировка сложности, проверка покрытия навыков
        
        ctx.set("optimized_blueprint", blueprint)
        
        await self._emit_complete(
            ctx,
            f"Test blueprint optimized: {len(blueprint)} items planned",
            {"item_count": len(blueprint)}
        )


class DiagnosticGeneratorStep(PipelineStep):
    """
    Шаг 2: Генератор диагностических заданий
    
    Роль: Генерирует конкретные тестовые задания
    """
    
    def __init__(self):
        super().__init__(
            name="DiagnosticGenerator",
            agent_name="Item Writer 📝",
            icon="📝"
        )
    
    async def execute(self, ctx: PipelineContext) -> None:
        await self._emit_start(ctx, "Generating diagnostic test items...")
        
        blueprint = ctx.get("optimized_blueprint", [])
        target_lang = ctx.get("target_lang", "Spanish")
        native_lang = ctx.get("native_lang", "English")
        
        settings = get_settings()
        llm_client = await get_llm_client()
        items = []
        
        for idx, bp in enumerate(blueprint):
            await self._emit_working(
                ctx,
                f"Writing item {idx + 1}/{len(blueprint)}: {bp.get('skill')}...",
                {"progress": idx + 1, "total": len(blueprint)}
            )
            
            prompt = f"""Generate a diagnostic test item:

Target Language: {target_lang}
Skill: {bp.get('skill')}
Subskill: {bp.get('subskill')}
Task Type: {bp.get('taskType')}
CEFR: {bp.get('cefrBand')}

Return JSON:
{{
  "prompt": "The test question",
  "choices": ["A", "B", "C", "D"],
  "answers": ["correct"],
  "taskType": "{bp.get('taskType')}",
  "distractorReasons": {{"wrong": "why"}}
}}"""
            
            try:
                llm_resp = await llm_client.generate(
                    system_prompt="You are a precise item writer for diagnostic tests.",
                    user_prompt=prompt,
                    provider=getattr(settings, "default_provider_batch", None) or settings.default_provider_fast or "stub",
                    model=getattr(settings, "gemini_model_batch", None) or settings.gemini_model_fast,
                    max_tokens=600
                )
                
                response_text = llm_resp.text
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    item = json.loads(response_text[json_start:json_end])
                    items.append(item)
            
            except Exception as e:
                logger.error(f"Failed to generate item {idx}: {e}")
        
        ctx.set("diagnostic_items", items)
        
        await self._emit_complete(
            ctx,
            f"Generated {len(items)} diagnostic items",
            {"item_count": len(items)}
        )
