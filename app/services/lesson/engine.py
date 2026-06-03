"""
Lesson engine for Duolingo-like language learning.

Handles lesson generation and grading using LLM with strict JSON validation.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from app.models.api import (
    Lesson,
    LessonGenerateRequest,
    LessonSubmitRequest,
    GradeResult,
    LessonSummary,
    Task,
    TaskType,
)
from app.core.llm.router import execute_llm_request
from app.core.util import job_id
from app.services.prompt_testing import (
    PromptType,
    get_prompt_for_test,
    get_prompt_test_manager,
    init_prompt_test_manager,
)
from app.core.llm.validator import validate_llm_json, ValidationResult


FALLBACK_LESSON_GENERATOR_PROMPT = """You are generating structured language-learning lessons.
Always return valid JSON with all required task fields and grading metadata."""

FALLBACK_LESSON_GENERATOR_COMPACT_PROMPT = """You are generating compact language-learning lessons.
Follow compact output format while preserving all task and grading requirements."""

FALLBACK_LESSON_GRADER_PROMPT = """You are grading language-learning answers.
Return strict JSON with correctness, score, feedback, and optional correctAnswer."""


def _resolve_prompts_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent / "prompts",
        Path(__file__).resolve().parents[3] / "prompts",
    ]
    required_files = ("lesson_generator.md", "lesson_generator_compact.md", "lesson_grader.md")
    for candidate in candidates:
        if candidate.exists() and all((candidate / file_name).exists() for file_name in required_files):
            return candidate
    fallback = candidates[0]
    logging.warning(
        "Lesson prompt directory could not be fully validated; using fallback path %s",
        fallback,
    )
    return fallback


def _load_prompt_file(prompt_file: str, fallback_text: str) -> str:
    prompt_path = PROMPTS_DIR / prompt_file
    try:
        content = prompt_path.read_text(encoding="utf-8").strip()
        if content:
            return content
        raise ValueError("prompt file is empty")
    except Exception as exc:
        logging.warning(
            "Failed to load prompt file %s (%s). Using built-in fallback prompt.",
            prompt_path,
            exc,
        )
        return fallback_text


def _ensure_prompt_content(prompt_content: str, fallback_text: str, prompt_name: str) -> str:
    if prompt_content and prompt_content.strip():
        return prompt_content
    logging.warning(
        "Prompt content for %s is empty. Using built-in fallback prompt.",
        prompt_name,
    )
    return fallback_text


# Load system prompts
PROMPTS_DIR = _resolve_prompts_dir()

# Initialize prompt testing system
try:
    init_prompt_test_manager(PROMPTS_DIR)
    logging.info("Prompt testing system initialized")
except Exception as e:
    logging.warning("Failed to initialize prompt testing system from %s: %s", PROMPTS_DIR, e)

# Legacy static prompt loading (fallback)
GENERATOR_PROMPT = _load_prompt_file("lesson_generator.md", FALLBACK_LESSON_GENERATOR_PROMPT)
GENERATOR_PROMPT_COMPACT = _load_prompt_file(
    "lesson_generator_compact.md",
    FALLBACK_LESSON_GENERATOR_COMPACT_PROMPT,
)
GRADER_PROMPT = _load_prompt_file("lesson_grader.md", FALLBACK_LESSON_GRADER_PROMPT)


def validate_lesson(lesson_data: dict, expected_length: int) -> tuple[bool, list[str]]:
    """
    Validate lesson structure and task requirements.
    
    Returns:
        (is_valid, list_of_error_messages)
    """
    errors = []
    
    # Validate top-level fields
    required_fields = ["lessonId", "title", "targetLang", "nativeLang", "level", "mode", "tasks"]
    for field in required_fields:
        if not lesson_data.get(field):
            errors.append(f"Missing required field: {field}")
    
    # Validate tasks array
    tasks = lesson_data.get("tasks", [])
    if not isinstance(tasks, list):
        errors.append("tasks must be an array")
        return False, errors
    
    if len(tasks) != expected_length:
        errors.append(f"Expected {expected_length} tasks, got {len(tasks)}")
    
    # Validate each task
    for idx, task in enumerate(tasks):
        task_errors = validate_task(task, idx)
        errors.extend(task_errors)
    
    return len(errors) == 0, errors


def validate_task(task: dict, index: int) -> list[str]:
    """Validate a single task based on its type."""
    errors = []
    prefix = f"Task[{index}]"
    
    # Common required fields
    required_common = ["id", "type", "prompt", "skill", "difficulty", "content", "grading"]
    for field in required_common:
        if field not in task:
            errors.append(f"{prefix}: missing {field}")
    
    if "difficulty" in task:
        diff = task["difficulty"]
        if not isinstance(diff, int) or diff < 1 or diff > 5:
            errors.append(f"{prefix}: difficulty must be 1-5, got {diff}")
    
    task_type = task.get("type")
    content = task.get("content", {})
    grading = task.get("grading", {})
    
    # Type-specific validation
    if task_type == "mcq":
        # MCQ must have choices
        choices = content.get("choices") or content.get("options")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            errors.append(f"{prefix}: mcq missing content.choices (non-empty array)")
        
        # Must have question or sourceText
        if not content.get("question") and not content.get("sourceText"):
            errors.append(f"{prefix}: mcq missing content.question or content.sourceText")
        
        # Validate correctChoiceIndex
        if "correctChoiceIndex" in grading:
            idx_val = grading["correctChoiceIndex"]
            if not isinstance(idx_val, int):
                errors.append(f"{prefix}: correctChoiceIndex must be integer")
            elif choices and (idx_val < 0 or idx_val >= len(choices)):
                errors.append(f"{prefix}: correctChoiceIndex {idx_val} out of range [0, {len(choices)-1}]")
        else:
            # Check for correctAnswer field as fallback
            if not grading.get("correctAnswer"):
                errors.append(f"{prefix}: mcq missing grading.correctChoiceIndex or grading.correctAnswer")
    
    elif task_type == "translate":
        # Validate sourceText
        source_text = content.get("sourceText") or content.get("sourceSentence")
        if not source_text or (isinstance(source_text, str) and not source_text.strip()):
            errors.append(f"{prefix}: translate missing content.sourceText (non-empty string)")
        
        # Validate targetLang (optional but recommended)
        target_lang = content.get("targetLang")
        if not target_lang or (isinstance(target_lang, str) and not target_lang.strip()):
            errors.append(f"{prefix}: translate missing content.targetLang (non-empty string)")
        
        # Validate grading
        accepted = grading.get("acceptedAnswers") or grading.get("accepted_variants", [])
        correct = grading.get("correctAnswer")
        if not accepted and not correct:
            errors.append(f"{prefix}: translate missing grading.acceptedAnswers or grading.correctAnswer")
        
        # Validate prompt exists
        if not task.get("prompt") or not task.get("prompt").strip():
            errors.append(f"{prefix}: translate missing task.prompt (non-empty string)")
    
    elif task_type == "fill_blank":
        sentence = content.get("sentenceWithBlank") or content.get("sentence")
        if not sentence:
            errors.append(f"{prefix}: fill_blank missing content.sentenceWithBlank")
        elif "__" not in sentence and "___" not in sentence and "_____" not in sentence:
            errors.append(f"{prefix}: fill_blank sentence must contain blank marker (__)")
        
        accepted = grading.get("acceptedAnswers") or grading.get("accepted_variants", [])
        correct = grading.get("correctAnswer")
        if not accepted and not correct:
            errors.append(f"{prefix}: fill_blank missing grading.acceptedAnswers or grading.correctAnswer")
    
    elif task_type == "word_order":
        tokens = content.get("tokens") or content.get("words")
        if not tokens or not isinstance(tokens, list) or len(tokens) < 2:
            errors.append(f"{prefix}: word_order missing content.tokens (array with 2+ items)")
        
        accepted = grading.get("acceptedSentence") or grading.get("acceptedAnswers") or grading.get("correctAnswer")
        if not accepted:
            errors.append(f"{prefix}: word_order missing grading.acceptedSentence or grading.correctAnswer")
    
    return errors


def auto_repair_lesson(lesson_data: dict) -> tuple[dict, list[str]]:
    """
    Attempt to auto-repair common LLM mistakes in lesson structure.
    
    Returns:
        (repaired_lesson_data, list_of_repairs_applied)
    """
    repairs = []
    tasks = lesson_data.get("tasks", [])
    
    for idx, task in enumerate(tasks):
        task_type = task.get("type")
        content = task.get("content", {})
        grading = task.get("grading", {})
        
        # Repair MCQ: move choices from wrong location
        if task_type == "mcq":
            if not content.get("choices"):
                # Check legacy locations
                if task.get("choices"):
                    content["choices"] = task["choices"]
                    repairs.append(f"Task[{idx}]: moved choices from task.choices to content.choices")
                elif task.get("options"):
                    content["choices"] = task["options"]
                    repairs.append(f"Task[{idx}]: moved options to content.choices")
                elif content.get("options"):
                    content["choices"] = content["options"]
                    repairs.append(f"Task[{idx}]: renamed content.options to content.choices")
            
            # Repair: move question from wrong location
            if not content.get("question") and not content.get("sourceText"):
                if task.get("question"):
                    content["question"] = task["question"]
                    repairs.append(f"Task[{idx}]: moved question to content.question")
                elif task.get("text"):
                    content["question"] = task["text"]
                    repairs.append(f"Task[{idx}]: moved text to content.question")
        
        # Repair translate: move sourceText from various locations
        elif task_type == "translate":
            if not content.get("sourceText") and not content.get("sourceSentence"):
                # Try legacy field locations
                if task.get("text") and task.get("text").strip():
                    content["sourceText"] = task["text"].strip()
                    repairs.append(f"Task[{idx}]: moved text to content.sourceText")
                elif task.get("sourceText") and task.get("sourceText").strip():
                    content["sourceText"] = task["sourceText"].strip()
                    repairs.append(f"Task[{idx}]: moved sourceText from task to content")
                elif task.get("question") and task.get("question").strip():
                    content["sourceText"] = task["question"].strip()
                    repairs.append(f"Task[{idx}]: moved question to content.sourceText")
                elif content.get("question") and content.get("question").strip():
                    content["sourceText"] = content["question"].strip()
                    repairs.append(f"Task[{idx}]: renamed content.question to content.sourceText")
                else:
                    # Try extracting from prompt (e.g., "Translate: 'Hello'")
                    prompt_text = task.get("prompt", "")
                    if prompt_text and ('"' in prompt_text or "'" in prompt_text):
                        import re
                        # Match quoted text
                        match = re.search(r"['\"]([^'\"]+)['\"]", prompt_text)
                        if match:
                            extracted = match.group(1).strip()
                            if extracted:
                                content["sourceText"] = extracted
                                repairs.append(f"Task[{idx}]: extracted sourceText from prompt")
            
            # Normalize sourceSentence -> sourceText
            if not content.get("sourceText") and content.get("sourceSentence"):
                content["sourceText"] = content["sourceSentence"]
                repairs.append(f"Task[{idx}]: renamed sourceSentence to sourceText")
        
        # Repair fill_blank: normalize sentence field
        elif task_type == "fill_blank":
            if not content.get("sentenceWithBlank"):
                if content.get("sentence"):
                    content["sentenceWithBlank"] = content["sentence"]
                    repairs.append(f"Task[{idx}]: renamed sentence to sentenceWithBlank")
                elif task.get("sentence"):
                    content["sentenceWithBlank"] = task["sentence"]
                    repairs.append(f"Task[{idx}]: moved sentence to content.sentenceWithBlank")
        
        # Repair word_order: normalize tokens field
        elif task_type == "word_order":
            if not content.get("tokens"):
                if content.get("words"):
                    content["tokens"] = content["words"]
                    repairs.append(f"Task[{idx}]: renamed words to tokens")
                elif task.get("words"):
                    content["tokens"] = task["words"]
                    repairs.append(f"Task[{idx}]: moved words to content.tokens")
            
            # Normalize grading: acceptedSentence -> correctAnswer
            if not grading.get("correctAnswer"):
                if grading.get("acceptedSentence"):
                    grading["correctAnswer"] = grading["acceptedSentence"]
                    repairs.append(f"Task[{idx}]: renamed acceptedSentence to correctAnswer")
                elif grading.get("acceptedAnswers") and isinstance(grading["acceptedAnswers"], list) and len(grading["acceptedAnswers"]) > 0:
                    grading["correctAnswer"] = grading["acceptedAnswers"][0]
                    repairs.append(f"Task[{idx}]: moved first acceptedAnswer to correctAnswer")
        
        # Update task content and grading
        task["content"] = content
        task["grading"] = grading
    
    lesson_data["tasks"] = tasks
    return lesson_data, repairs


def generate_lesson(
    req: LessonGenerateRequest,
    persona_prompt: str,
    provider: str = "gemini",
    model: str = "gemini-2.0-flash-exp",
    optimize_mode: bool = False,
    user_id: str = "anonymous"
) -> Lesson:
    """
    Generate a lesson using LLM with JSON validation and retries.
    
    Args:
        req: Lesson generation parameters
        persona_prompt: Resolved persona system prompt
        provider: LLM provider name
        model: Model identifier
        optimize_mode: Whether to use compact format
        user_id: User ID for A/B testing and logging
        
    Returns:
        Validated Lesson object
        
    Raises:
        ValueError: If generation fails after retries
    """
    lesson_id = job_id("lesson")
    start_time = time.perf_counter()
    
    # Determine which prompt to use via testing system
    prompt_type = PromptType.LESSON_GENERATOR_COMPACT if optimize_mode else PromptType.LESSON_GENERATOR
    prompt_version = "baseline"  # Default
    
    try:
        # Get prompt through testing system
        generator_prompt_content, prompt_version = get_prompt_for_test(prompt_type, user_id)
        logging.info(f"Using {prompt_version} version of {prompt_type.value} prompt for user {user_id}")
    except Exception as e:
        # Fallback to static prompts
        logging.warning(f"Failed to get prompt from testing system: {e}, falling back to static")
        generator_prompt_content = GENERATOR_PROMPT_COMPACT if optimize_mode else GENERATOR_PROMPT
        prompt_version = "baseline"

    generator_prompt_content = _ensure_prompt_content(
        generator_prompt_content,
        FALLBACK_LESSON_GENERATOR_COMPACT_PROMPT if optimize_mode else FALLBACK_LESSON_GENERATOR_PROMPT,
        prompt_type.value,
    )
    
    
    # Choose format based on optimize_mode
    if optimize_mode:
        # Use compact format to save tokens
        user_prompt = f"""Generate a {req.mode} lesson for learning {req.target_lang} (learner speaks {req.native_lang}).

Level: {req.level}
Topic: {req.topic or "general"}
Number of tasks: {req.lesson_length}

Create exactly {req.lesson_length} tasks using the compact format. Mix difficulty levels appropriately for {req.level} level.
All prompts should be in {req.native_lang}. All content should teach {req.target_lang}."""

        # Use compact system prompt (from testing system)
        system_prompt = f"""{persona_prompt}

---
COMPACT LESSON GENERATION MODE:
{generator_prompt_content}

Remember: You must maintain your persona's tone while strictly following the compact output format."""
    else:
        # Use original JSON format
        user_prompt = f"""Generate a {req.mode} lesson for learning {req.target_lang} (learner speaks {req.native_lang}).

Level: {req.level}
Topic: {req.topic or "general"}
Number of tasks: {req.lesson_length}

Requirements:
- Create exactly {req.lesson_length} tasks
- Use task types: mcq, translate, fill_blank, word_order
- Mix difficulty levels appropriately for {req.level} level
- All prompts should be in {req.native_lang}
- All content should teach {req.target_lang}

Output a valid JSON object matching this structure:
{{
  "lessonId": "{lesson_id}",
  "mode": "{req.mode}",
  "targetLang": "{req.target_lang}",
  "nativeLang": "{req.native_lang}",
  "level": "{req.level}",
  "topic": "{req.topic or 'general'}",
  "title": "...",
  "tasks": [...]
}}

IMPORTANT: Return ONLY the JSON object. No markdown, no code blocks, no extra text."""

        # Use original system prompt (from testing system)
        system_prompt = f"""{persona_prompt}

---
LESSON GENERATION MODE:
{generator_prompt_content}

Remember: You must maintain your persona's tone while strictly following the JSON output format."""

    max_retries = 2
    last_error = None
    start_time = time.perf_counter()
    
    for attempt in range(max_retries + 1):
        try:
            # Call LLM
            response_text = execute_llm_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                provider=provider,
                model=model
            )
            
            # Estimate token usage (rough approximation: ~4 chars per token)
            estimated_input_tokens = (len(system_prompt) + len(user_prompt)) // 4
            estimated_output_tokens = len(response_text) // 4
            estimated_total_tokens = estimated_input_tokens + estimated_output_tokens
            
            # Parse response based on format
            if optimize_mode:
                # Parse compact format
                from app.core.compact_parser import parse_compact_lesson
                
                # Build request data for parser
                req_data = {
                    "mode": req.mode,
                    "target_lang": req.target_lang,
                    "native_lang": req.native_lang,
                    "level": req.level,
                    "topic": req.topic
                }
                
                lesson_data = parse_compact_lesson(response_text, lesson_id, req_data)
                logging.info(f"Parsed compact lesson format: {len(lesson_data.get('tasks', []))} tasks")
            else:
                # Parse JSON format (original)
                cleaned = response_text.strip()
                if cleaned.startswith("```"):
                    # Extract JSON from code block
                    lines = cleaned.split("\n")
                    start_idx = 1 if lines[0].startswith("```") else 0
                    end_idx = len(lines)
                    for i in range(len(lines) - 1, -1, -1):
                        if lines[i].strip().startswith("```"):
                            end_idx = i
                            break
                    cleaned = "\n".join(lines[start_idx:end_idx])
                
                # Parse JSON
                lesson_data = json.loads(cleaned)
            
            # Apply targetLang fallback for translate tasks BEFORE validation
            for task in lesson_data.get("tasks", []):
                if task.get("type") == "translate":
                    content = task.get("content", {})
                    if not content.get("targetLang"):
                        content["targetLang"] = req.target_lang
                        task["content"] = content
                
                # For MCQ: auto-compute correctChoiceIndex if missing
                if task.get("type") == "mcq":
                    grading = task.get("grading", {})
                    content = task.get("content", {})
                    choices = content.get("choices", [])
                    correct_answer = grading.get("correctAnswer")
                    
                    # If correctChoiceIndex is missing but we have choices and correctAnswer
                    if grading.get("correctChoiceIndex") is None and choices and correct_answer:
                        # Try to find the correct answer in choices (case-insensitive)
                        correct_lower = correct_answer.strip().lower()
                        for idx, choice in enumerate(choices):
                            if choice.strip().lower() == correct_lower:
                                grading["correctChoiceIndex"] = idx
                                task["grading"] = grading
                                break
            
            # ALWAYS run auto-repair BEFORE validation to normalize data structure
            # This ensures Pydantic-required fields (like correctAnswer) are present
            repaired_data, repairs = auto_repair_lesson(lesson_data)
            
            if repairs:
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                logging.info(
                    "Lesson auto-repair applied",
                    extra={
                        "event": "lesson_autorepair_applied",
                        "lesson_id": lesson_id,
                        "attempt_number": attempt + 1,
                        "repaired_fields": repairs,
                        "duration_ms": duration_ms
                    }
                )
                lesson_data = repaired_data
            
            # Strict validation AFTER auto-repair
            is_valid, validation_errors = validate_lesson(lesson_data, req.lesson_length)
            
            if not is_valid:
                # Log validation failure
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                logging.warning(
                    "Lesson validation failed",
                    extra={
                        "event": "lesson_validation_failed",
                        "lesson_id": lesson_id,
                        "attempt_number": attempt + 1,
                        "invalid_reasons": validation_errors[:10],  # Limit to first 10
                        "duration_ms": duration_ms
                    }
                )
                
                # Build specific error message for retry
                error_summary = "; ".join(validation_errors[:5])
                raise ValueError(f"Validation failed: {error_summary}")
            
            # Validate using Pydantic (final check with better error handling)
            try:
                lesson = Lesson.model_validate(lesson_data)
            except Exception as e:
                # Log Pydantic validation failure with details
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                logging.error(
                    "Pydantic model validation failed",
                    extra={
                        "event": "lesson_pydantic_validation_failed",
                        "lesson_id": lesson_id,
                        "attempt_number": attempt + 1,
                        "error": str(e),
                        "duration_ms": duration_ms
                    }
                )
                raise ValueError(f"Schema validation failed: {str(e)}")
            
            # Calculate execution time and log test result
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            
            # Log to prompt testing system if enabled
            try:
                test_manager = get_prompt_test_manager()
                
                # Prepare request data for logging
                request_data = {
                    "mode": req.mode,
                    "target_lang": req.target_lang,
                    "native_lang": req.native_lang,
                    "level": req.level,
                    "lesson_length": req.lesson_length,
                    "topic": req.topic,
                    "optimize_mode": optimize_mode,
                    "provider": provider,
                    "model": model
                }
                
                # Prepare response data (lesson summary for comparison)
                response_data = {
                    "lesson_id": lesson.lessonId,
                    "title": lesson.title,
                    "task_count": len(lesson.tasks),
                    "task_types": [task.type for task in lesson.tasks],
                    "success": True
                }
                
                test_manager.log_test_result(
                    prompt_type=prompt_type,
                    prompt_version=prompt_version,
                    user_id=user_id,
                    request_data=request_data,
                    response_data=response_data,
                    execution_time_ms=duration_ms,
                    success=True,
                    tokens_used=estimated_total_tokens,
                    input_tokens=estimated_input_tokens,
                    output_tokens=estimated_output_tokens
                )
                
                logging.info(f"Logged test result for {prompt_version} version (took {duration_ms}ms)")
                
            except Exception as e:
                logging.warning(f"Failed to log prompt test result: {e}")
            
            logging.info(f"Successfully generated lesson {lesson_id} with {len(lesson.tasks)} tasks (took {duration_ms}ms)")
            return lesson
            
        except (json.JSONDecodeError, ValueError, Exception) as e:
            last_error = e
            error_msg = str(e)
            logging.warning(f"Lesson generation attempt {attempt + 1} failed: {error_msg}")
            
            if attempt < max_retries:
                # Build specific correction prompt based on error type
                correction = "\n\nPREVIOUS ATTEMPT FAILED. "
                
                if "mcq" in error_msg.lower() and "choices" in error_msg.lower():
                    correction += """For MCQ tasks you MUST include:
- content.choices: array of 3-4 strings (answer options)
- content.question: the question text
- grading.correctChoiceIndex: integer (0 to choices.length-1)

Example MCQ task:
{
  "type": "mcq",
  "content": {
    "question": "What color is 'rojo'?",
    "choices": ["Red", "Blue", "Green", "Yellow"]
  },
  "grading": {
    "correctChoiceIndex": 0,
    "correctAnswer": "Red",
    "tip": "Think of a rose"
  }
}
"""
                elif "translate" in error_msg.lower():
                    correction += """For translate tasks you MUST include:
- content.sourceText: the text to translate (non-empty string)
- content.targetLang: target language name (e.g., "Spanish", "French")
- grading.correctAnswer: the correct translation (string)
- grading.acceptedVariants: alternative valid translations (string array, can be empty)

Example translate task:
{
  "type": "translate",
  "prompt": "Translate: 'Hello, how are you?'",
  "content": {
    "sourceText": "Hello, how are you?",
    "targetLang": "Spanish"
  },
  "grading": {
    "correctAnswer": "Hola, ¿cómo estás?",
    "acceptedVariants": ["Hola, ¿cómo está?", "Hola, ¿qué tal?"],
    "tip": "Remember the informal 'tú' form"
  }
}

CRITICAL: content.sourceText must be the actual text to translate, not empty or null.
"""
                elif "fill_blank" in error_msg.lower():
                    correction += """For fill_blank tasks you MUST include:
- content.sentenceWithBlank: sentence with _____ or __
- grading.correctAnswer and/or grading.acceptedAnswers

Example:
{
  "type": "fill_blank",
  "content": {
    "sentenceWithBlank": "Yo _____ (I am) estudiante."
  },
  "grading": {
    "correctAnswer": "soy",
    "acceptedVariants": [],
    "tip": "Use the verb 'ser'"
  }
}
"""
                elif "word_order" in error_msg.lower():
                    correction += """For word_order tasks you MUST include:
- content.tokens: array of words to arrange
- grading.correctAnswer or grading.acceptedSentence

Example:
{
  "type": "word_order",
  "content": {
    "tokens": ["el", "gato", "es", "negro"]
  },
  "grading": {
    "correctAnswer": "El gato es negro",
    "tip": "Subject-verb-adjective order"
  }
}
"""
                else:
                    correction += f"Error: {error_msg}\n"
                
                correction += "\nRETURN VALID JSON ONLY. Start with { and end with }"
                user_prompt += correction
            else:
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                
                # Log failed test result
                try:
                    test_manager = get_prompt_test_manager()
                    
                    request_data = {
                        "mode": req.mode,
                        "target_lang": req.target_lang,
                        "native_lang": req.native_lang,
                        "level": req.level,
                        "lesson_length": req.lesson_length,
                        "topic": req.topic,
                        "optimize_mode": optimize_mode,
                        "provider": provider,
                        "model": model
                    }
                    
                    response_data = {"error": error_msg, "success": False}
                    
                    test_manager.log_test_result(
                        prompt_type=prompt_type,
                        prompt_version=prompt_version,
                        user_id=user_id,
                        request_data=request_data,
                        response_data=response_data,
                        execution_time_ms=duration_ms,
                        success=False,
                        error=error_msg,
                        tokens_used=estimated_total_tokens if 'estimated_total_tokens' in locals() else None,
                        input_tokens=estimated_input_tokens if 'estimated_input_tokens' in locals() else None,
                        output_tokens=estimated_output_tokens if 'estimated_output_tokens' in locals() else None
                    )
                    
                    logging.info(f"Logged failed test result for {prompt_version} version")
                    
                except Exception as e:
                    logging.warning(f"Failed to log failed prompt test result: {e}")
                
                logging.error(
                    "Lesson generation failed after all retries",
                    extra={
                        "event": "lesson_generation_failed",
                        "lesson_id": lesson_id,
                        "error": error_msg,
                        "attempts": max_retries + 1,
                        "duration_ms": duration_ms
                    }
                )
                raise ValueError(f"lesson_generation_failed: {error_msg}")


def grade_submission(
    task: Task,
    user_answer: str,
    persona_prompt: str,
    provider: str = "gemini",
    model: str = "gemini-2.0-flash-exp"
) -> GradeResult:
    """
    Grade a task submission using LLM or direct comparison.
    
    For MCQ tasks, uses direct string comparison (case-insensitive).
    For other tasks (translate, fill_blank, word_order), uses LLM grading.
    
    Args:
        task: The task being graded
        user_answer: User's submitted answer
        persona_prompt: Resolved persona system prompt
        provider: LLM provider name
        model: Model identifier
        
    Returns:
        Validated GradeResult
        
    Raises:
        ValueError: If grading fails after retries
    """
    # For MCQ tasks, use direct comparison instead of LLM
    if task.type == TaskType.mcq:
        # Normalize text: strip whitespace, lowercase, remove punctuation
        def normalize(text: str) -> str:
            import re
            text = text.strip().lower()
            # Remove common punctuation
            text = re.sub(r'[.!?]$', '', text)
            return text
        
        user_normalized = normalize(user_answer)
        
        # Determine the correct answer from choices using correctChoiceIndex
        # This is the actual choice from the MCQ options, not the English translation
        correct_choice = None
        if hasattr(task.content, 'choices') and task.content.choices:
            # Try to get correct choice by index first (most reliable)
            if hasattr(task.grading, 'correct_choice_index'):
                idx = task.grading.correct_choice_index
                if idx is not None and 0 <= idx < len(task.content.choices):
                    correct_choice = task.content.choices[idx]
        
        # If no valid index, fall back to comparing with correct_answer field
        if not correct_choice:
            correct_choice = task.grading.correct_answer
        
        correct_normalized = normalize(correct_choice)
        
        # Check if answer matches correct choice or any accepted variant
        is_correct = user_normalized == correct_normalized
        if not is_correct and task.grading.accepted_variants:
            is_correct = any(
                user_normalized == normalize(variant) 
                for variant in task.grading.accepted_variants
            )
        
        if is_correct:
            return GradeResult(
                task_id=task.id,
                correct=True,
                score=1.0,
                feedback="Correct! Well done!",
                correct_answer=None
            )
        else:
            return GradeResult(
                task_id=task.id,
                correct=False,
                score=0.0,
                feedback=f"Not quite. {task.grading.tip}",
                correct_answer=correct_choice
            )
    
    # For non-MCQ tasks, use LLM grading
    # Build user prompt with task context and grading rules
    user_prompt = f"""Grade this language learning task submission.

Task Type: {task.type}
Task Prompt: {task.prompt}
Skill: {task.skill}
Difficulty: {task.difficulty}

User Answer: "{user_answer}"

Grading Rules:
- Correct Answer: {task.grading.correct_answer}
- Accepted Variants: {', '.join(task.grading.accepted_variants) if task.grading.accepted_variants else 'none'}
- Partial Credit Keywords: {', '.join(task.grading.partial_credit_keywords) if task.grading.partial_credit_keywords else 'none'}
- Tip for wrong answer: {task.grading.tip}

Output a valid JSON object:
{{
  "taskId": "{task.id}",
  "correct": true or false,
  "score": 0.0 to 1.0,
  "feedback": "...",
  "correctAnswer": "..." or null
}}

IMPORTANT: Return ONLY the JSON object. No markdown, no code blocks."""

    # Combine system prompts
    grader_prompt_content = _ensure_prompt_content(
        GRADER_PROMPT,
        FALLBACK_LESSON_GRADER_PROMPT,
        PromptType.LESSON_GRADER.value,
    )

    system_prompt = f"""{persona_prompt}

---
GRADING MODE:
{grader_prompt_content}

Remember: Maintain your persona's encouraging tone while strictly following the JSON output format."""

    max_retries = 2
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            response_text = execute_llm_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                provider=provider,
                model=model
            )
            
            # Use LLM validator for robust parsing
            validation_result = validate_llm_json(
                response_text,
                GradeResult,
                context={"task_id": task.id, "task_type": task.type, "attempt": attempt + 1}
            )
            
            if validation_result.is_valid:
                grade = validation_result.data
                if validation_result.warnings:
                    logging.info(f"Grading validation warnings: {', '.join(validation_result.warnings)}")
                logging.info(f"Successfully graded task {task.id}: correct={grade.correct}, score={grade.score}")
                return grade
            else:
                # Validation failed - use correction prompt for retry
                error_msg = validation_result.error
                logging.warning(f"Grading validation failed: {error_msg}")
                
                if attempt < max_retries and validation_result.correction_prompt:
                    user_prompt += "\n\n" + validation_result.correction_prompt
                    continue
                else:
                    raise ValueError(error_msg)
            
        except Exception as e:
            last_error = e
            logging.warning(f"Grading attempt {attempt + 1} failed unexpectedly: {e}")
            
            if attempt < max_retries:
                user_prompt += f"\n\nPREVIOUS ATTEMPT FAILED: {str(e)}\nRETURN VALID JSON ONLY."
            else:
                logging.error(f"Grading failed after {max_retries + 1} attempts: {last_error}")
                raise ValueError(f"grading_failed: {last_error}")


def generate_lesson_summary(
    lesson: Lesson,
    attempts: list[tuple[str, bool, float]],  # (task_id, correct, score)
    persona_prompt: str,
    provider: str = "gemini",
    model: str = "gemini-2.0-flash-exp"
) -> LessonSummary:
    """
    Generate personalized lesson summary with encouragement.
    
    Args:
        lesson: The completed lesson
        attempts: List of (task_id, correct, score) tuples
        persona_prompt: Resolved persona system prompt
        provider: LLM provider
        model: Model identifier
        
    Returns:
        LessonSummary with personalized encouragement
    """
    correct_count = sum(1 for _, correct, _ in attempts if correct)
    total_score = sum(score for _, _, score in attempts)
    score_percentage = (total_score / len(attempts)) * 100 if attempts else 0.0
    
    # Build encouragement prompt
    user_prompt = f"""Generate a brief, encouraging message for a language learner who just completed a lesson.

Lesson: {lesson.title}
Level: {lesson.level}
Total Tasks: {len(attempts)}
Correct: {correct_count}
Score: {score_percentage:.1f}%

Message should:
- Be 1-2 sentences
- Match the persona's tone
- Acknowledge performance (great/good/keep practicing)
- Encourage continued learning

Return ONLY the encouragement text (no JSON needed)."""

    try:
        encouragement = execute_llm_request(
            system_prompt=persona_prompt,
            user_prompt=user_prompt,
            provider=provider,
            model=model
        ).strip()
    except Exception as e:
        logging.warning(f"Failed to generate encouragement: {e}")
        # Fallback encouragement
        if score_percentage >= 80:
            encouragement = "Excellent work! You're making great progress."
        elif score_percentage >= 60:
            encouragement = "Good effort! Keep practicing and you'll master this."
        else:
            encouragement = "Keep going! Every mistake is a learning opportunity."
    
    return LessonSummary(
        lesson_id=lesson.lesson_id,
        total_tasks=len(attempts),
        correct_count=correct_count,
        score_percentage=round(score_percentage, 1),
        completed=True,
        encouragement=encouragement
    )


