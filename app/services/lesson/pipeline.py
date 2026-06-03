"""
Lesson generation using pipeline with Exercise Diversity.

Integrates the Pipeline orchestrator (LessonPlanner, ContentCreator, Validator)
with the main lesson_engine to ensure 10 exercises with strict distribution.
"""
import json
import logging
from typing import Optional

from app.models.api import Lesson, Task
from app.services.pipeline.pipeline.core import PipelineContext, PipelineOrchestrator
from app.services.pipeline.pipeline.steps import LessonPlannerStep, LessonContentStep, LessonValidatorStep
from app.infrastructure.llm.client import get_llm_client
from app.services.llm.contracts import summarize_ledger_events
from app.settings import get_settings

logger = logging.getLogger(__name__)



async def generate_lesson_with_pipeline(
    target_lang: str,
    native_lang: str,
    cefr_level: str,
    topic: str,
    focus: str = "grammar",
    mode: str = "learning_path",
    node_id: str = None,
    unit_id: str = None,
    lesson_length: int = 10,
    xp_reward: int = 15,
    max_questions: int = 10,
    time_limit_seconds: int = 600,
    user_id: str = None,
    trace_id: str | None = None,
    session_id: str | None = None,
    job_id: str | None = None,
) -> dict:
    """
    Generate lesson using pipeline with Exercise Diversity enforcement.
    
    Returns:
        Dictionary with lesson_content (exercises array with 10 items)
    """
    
    ctx = PipelineContext({
        "target_lang": target_lang,
        "native_lang": native_lang,
        "cefr_level": cefr_level,
        "topic": topic,
        "focus": focus,
        "mode": mode,
        "node_id": node_id,
        "unit_id": unit_id,
        "lesson_length": lesson_length,
        "xp_reward": xp_reward,
        "max_questions": max_questions,
        "time_limit_seconds": time_limit_seconds,
        "user_id": user_id,
        "trace_id": trace_id,
        "session_id": session_id,
        "job_id": job_id,
        "ledger_events": [],
    })
    
    steps = [
        LessonPlannerStep(),
        LessonContentStep(),
        LessonValidatorStep()
    ]
    
    orchestrator = PipelineOrchestrator(steps)
    await orchestrator.run(ctx)
    
    # Extract lesson content
    lesson_content = ctx.get("lesson_content") or {}
    validation = ctx.get("validation_result") or {}
    
    # Accept APPROVE, NEEDS_REVIEW, or REVISE with score >= 60 (relaxed for learning path)
    recommendation = validation.get("recommendation", "")
    score = validation.get("score", 0)
    success = recommendation in ["APPROVE", "NEEDS_REVIEW", "REVISE"] and score >= 60
    cost_summary = summarize_ledger_events(list(ctx.get("ledger_events", [])))
    
    return {
        "lesson_content": lesson_content,
        "validation": validation,
        "success": success,
        "error": None if success else f"Validation failed: {recommendation} (score: {score})",
        "cost_summary": cost_summary,
    }


async def generate_lesson_from_pipeline(
    target_lang: str,
    native_lang: str,
    cefr_level: str,
    topic: str,
    focus: str = "grammar",
    mode: str = "learning_path",
    node_id: str = None,
    unit_id: str = None,
    lesson_length: int = 10,
    xp_reward: int = 15,
    trace_id: str | None = None,
    session_id: str | None = None,
    job_id: str | None = None,
) -> dict:
    """
    Async wrapper for pipeline-based lesson generation.
    
    For use in async endpoints (main.py).
    """
    try:
        result = await generate_lesson_with_pipeline(
            target_lang=target_lang,
            native_lang=native_lang,
            cefr_level=cefr_level,
            topic=topic,
            focus=focus,
            mode=mode,
            node_id=node_id,
            unit_id=unit_id,
            lesson_length=lesson_length,
            xp_reward=xp_reward,
            trace_id=trace_id,
            session_id=session_id,
            job_id=job_id,
        )
        return result
    except Exception as e:
        logger.error(f"Pipeline generation failed: {e}")
        raise


def convert_pipeline_lesson_to_model(
    lesson_content: dict,
    lesson_id: str,
    mode: str = "comprehensive"
) -> Lesson:
    """
    Convert pipeline output (with exercises array) to Lesson model.
    
    Args:
        lesson_content: Output from pipeline (has 'exercises' array)
        lesson_id: Unique lesson ID
        mode: Lesson mode (vocabulary, grammar, comprehensive)
        
    Returns:
        Lesson object compatible with existing system
    """
    
    # Map pipeline exercise types to Task model types
    TYPE_MAP = {
        "mcq": "mcq",
        "translation": "translate",
        "word_bank": "word_order",  # Arrange words to form sentence
        "listening_mimic": "word_order"  # Also word arrangement for pronunciation
    }
    
    # Extract exercises from pipeline output
    exercises = lesson_content.get("exercises", [])
    target_lang = lesson_content.get("targetLang", "")
    native_lang = lesson_content.get("nativeLang", "")
    
    # Convert pipeline exercises to Task objects
    tasks = []
    for exercise in exercises:
        try:
            exercise_type = exercise.get("type", "mcq")
            mapped_type = TYPE_MAP.get(exercise_type, "mcq")
            
            # Build content object based on exercise type
            content = {}
            
            if exercise_type == "mcq":
                # MCQ needs: question, options (list of choices)
                content = {
                    "question": exercise.get("question") or exercise.get("prompt", ""),
                    "options": exercise.get("choices") or exercise.get("options", [])
                }
            elif exercise_type == "translation":
                # Translation needs: sourceText (NOT sourceSentence), targetLang
                content = {
                    "sourceText": exercise.get("sourceText") or exercise.get("sourceSentence", ""),
                    "targetLang": target_lang
                }
            elif exercise_type == "word_bank":
                # Word bank needs: words (array to arrange), sentence (reference/target)
                content = {
                    "words": exercise.get("tokens") or exercise.get("words", []),
                    "sentence": exercise.get("correctSentence") or exercise.get("englishSentence", "")
                }
            elif exercise_type == "listening_mimic":
                # Listening needs: words (to arrange), sentence (target pronunciation)
                content = {
                    "words": exercise.get("words") or exercise.get("tokens", []),
                    "sentence": exercise.get("dialogue") or exercise.get("sentence", "")
                }
            
            # Fallback: if content is directly nested in exercise
            if not content or all(v is None or v == [] or v == "" for v in content.values()):
                content = exercise.get("content", {})
            
            # Build grading object
            grading = exercise.get("grading", {})
            if "correctAnswer" not in grading:
                grading["correctAnswer"] = (
                    exercise.get("correctAnswer") or 
                    exercise.get("correctSentence") or
                    exercise.get("correctPronunciation") or
                    ""
                )
            if "tip" not in grading:
                grading["tip"] = exercise.get("tip", "")
            
            # For MCQ, ensure correctChoiceIndex
            if exercise_type == "mcq" and "correctChoiceIndex" not in grading:
                grading["correctChoiceIndex"] = exercise.get("correctChoiceIndex", 0)
            
            # For translations, add acceptedVariants
            if exercise_type == "translation" and "acceptedVariants" not in grading:
                grading["acceptedVariants"] = exercise.get("acceptedVariants", [])
            
            task = Task(
                id=exercise.get("id", f"task_{len(tasks)+1}"),
                type=mapped_type,
                prompt=exercise.get("prompt", ""),
                skill=exercise.get("skill", ""),
                difficulty=exercise.get("difficulty", 1),
                content=content,
                grading=grading
            )
            tasks.append(task)
        except Exception as e:
            logger.warning(f"Failed to convert exercise {exercise.get('id')}: {e}")
            continue
    
    # Build Lesson object
    lesson = Lesson(
        lesson_id=lesson_id,
        mode=mode,
        target_lang=lesson_content.get("targetLang", "Spanish"),
        native_lang=lesson_content.get("nativeLang", "English"),
        level=lesson_content.get("level", "A1"),
        topic=lesson_content.get("topic", "General"),
        title=lesson_content.get("title", "Pipeline Lesson"),
        tasks=tasks
    )
    
    return lesson


