"""
Repair functions for common LLM output issues.
Automatically fixes missing fields, wrong formats, etc.
"""

import json
import logging
import hashlib
from typing import Dict, Any, List, Optional, Union
from .models import (
    BaseExercise as Exercise,
    MCQExercise,
    TranslationExercise,
    WordBankExercise,
    ListeningMimicExercise,
    FillBlankExercise,
    CheckpointExercise,
    LearningPathLesson,
    PlacementTest,
    AdHocLesson,
)

logger = logging.getLogger(__name__)

VALID_SKILLS = {
    "vocabulary",
    "grammar",
    "translation",
    "pronunciation",
    "listening",
    "reading",
    "writing",
}

SKILL_ALIASES = {
    "word_order": "grammar",
    "wordorder": "grammar",
    "word_bank": "grammar",
    "wordbank": "grammar",
    "comprehensive": "reading",
    "speaking": "pronunciation",
    "listening_comprehension": "listening",
    "reading_comprehension": "reading",
}


def normalize_skill(value: Any, default: str) -> str:
    """Normalize common LLM skill labels to the supported schema enum."""
    raw = str(value or default).strip().lower()
    normalized = SKILL_ALIASES.get(raw, raw)
    return normalized if normalized in VALID_SKILLS else default


def grading_value(data: Dict[str, Any], key: str, default: Any = None) -> Any:
    grading = data.get("grading")
    if isinstance(grading, dict) and key in grading:
        return grading[key]
    return default


def repair_exercise(exercise_data: Dict[str, Any]) -> Optional[Exercise]:
    """
    Repair a single exercise by fixing common issues.
    Returns repaired Exercise or None if unrepairable.
    """
    try:
        exercise_type = exercise_data.get('type', '').lower()

        # Normalize type names
        type_mapping = {
            'mcq': 'mcq',
            'multiple_choice': 'mcq',
            'translation': 'translation',
            'translate': 'translation',
            'word_bank': 'word_bank',
            'wordbank': 'word_bank',
            'word_order': 'word_bank',
            'listening_mimic': 'listening_mimic',
            'listening': 'listening_mimic',
            'pronunciation': 'listening_mimic',
            'fill_blank': 'fill_blank',
            'fillblank': 'fill_blank',
            'checkpoint': 'checkpoint'
        }
        exercise_type = type_mapping.get(exercise_type, exercise_type)

        if exercise_type == 'mcq':
            return repair_mcq_exercise(exercise_data)
        elif exercise_type == 'translation':
            return repair_translation_exercise(exercise_data)
        elif exercise_type == 'word_bank':
            return repair_word_bank_exercise(exercise_data)
        elif exercise_type == 'listening_mimic':
            return repair_listening_exercise(exercise_data)
        elif exercise_type == 'fill_blank':
            return repair_fill_blank_exercise(exercise_data)
        elif exercise_type == 'checkpoint':
            return repair_checkpoint_exercise(exercise_data)
        else:
            logger.warning(f"Unknown exercise type: {exercise_type}")
            return None

    except Exception as e:
        logger.warning(f"Failed to repair exercise {exercise_data.get('id')}: {e}")
        return None


def repair_mcq_exercise(data: Dict[str, Any]) -> Optional[MCQExercise]:
    """Repair MCQ exercise"""
    try:
        # Ensure choices is a list of 4 strings
        choices = data.get('choices', data.get('options', []))
        if not isinstance(choices, list) or len(choices) < 4:
            # Try to extract from other fields or create defaults
            if 'choice1' in data and 'choice2' in data:
                choices = [data[f'choice{i}'] for i in range(1, 5) if f'choice{i}' in data]
            else:
                choices = ["Option A", "Option B", "Option C", "Option D"]

        # Ensure correct_choice_index is valid
        correct_index = data.get('correctChoiceIndex', data.get('correct_choice_index', 0))
        if not isinstance(correct_index, int) or not (0 <= correct_index < len(choices)):
            correct_index = 0

        # Get correct answer
        correct_answer = data.get('correctAnswer', data.get('correct_answer', choices[correct_index] if choices else ""))

        repaired_data = {
            'id': data.get('id', f'mcq_{hash(str(data))}'),
            'type': 'mcq',
            'prompt': data.get('prompt', 'Choose the correct answer'),
            'skill': normalize_skill(data.get('skill'), 'vocabulary'),
            'difficulty': data.get('difficulty', 1),
            'question': data.get('question', data.get('prompt', 'Question?')),
            'choices': choices[:4],  # Ensure exactly 4
            'correctChoiceIndex': correct_index,
            'correct_answer': correct_answer,
            'tip': data.get('tip', grading_value(data, 'tip', ''))
        }

        return MCQExercise(**repaired_data)
    except Exception as e:
        logger.error(f"Failed to repair MCQ: {e}")
        return None


def repair_translation_exercise(data: Dict[str, Any]) -> Optional[TranslationExercise]:
    """Repair translation exercise"""
    try:
        # Map various source text field names
        source_text = (
            data.get('sourceText') or
            data.get('source_text') or
            data.get('sourceSentence') or
            data.get('source_sentence') or
            data.get('text') or
            data.get('phrase', '')
        )

        if not source_text.strip():
            logger.warning("Translation exercise missing source text")
            return None

        repaired_data = {
            'id': data.get('id', f'translation_{hash(str(data))}'),
            'type': 'translation',
            'prompt': data.get('prompt', 'Translate the text'),
            'skill': normalize_skill(data.get('skill'), 'translation'),
            'difficulty': data.get('difficulty', 1),
            'sourceText': source_text,
            'targetLang': data.get('targetLang', data.get('target_lang', 'Spanish')),
            'correct_answer': data.get('correctAnswer', data.get('correct_answer', grading_value(data, 'correctAnswer', ''))),
            'acceptedVariants': data.get('acceptedVariants', data.get('accepted_variants', grading_value(data, 'acceptedVariants', []))),
            'tip': data.get('tip', grading_value(data, 'tip', ''))
        }

        return TranslationExercise(**repaired_data)
    except Exception as e:
        logger.error(f"Failed to repair Translation: {e}")
        return None


def repair_word_bank_exercise(data: Dict[str, Any]) -> Optional[WordBankExercise]:
    """Repair word bank exercise"""
    try:
        words = data.get('words', data.get('tokens', []))
        if not isinstance(words, list) or len(words) < 3:
            # Try to extract from sentence
            sentence = data.get('sentence', '')
            if sentence:
                words = sentence.split()
            else:
                words = ['word1', 'word2', 'word3']

        sentence = data.get('sentence', data.get('correctSentence', ' '.join(words)))
        correct_answer = data.get('correctAnswer', data.get('correct_answer', sentence))

        repaired_data = {
            'id': data.get('id', f'word_bank_{hash(str(data))}'),
            'type': 'word_bank',
            'prompt': data.get('prompt', 'Arrange the words'),
            'skill': normalize_skill(data.get('skill'), 'grammar'),
            'difficulty': data.get('difficulty', 1),
            'words': words,
            'sentence': sentence,
            'correctAnswer': correct_answer,
            'tip': data.get('tip', grading_value(data, 'tip', ''))
        }

        return WordBankExercise(**repaired_data)
    except Exception as e:
        logger.error(f"Failed to repair Word Bank: {e}")
        return None


def repair_listening_exercise(data: Dict[str, Any]) -> Optional[ListeningMimicExercise]:
    """Repair listening mimic exercise"""
    try:
        sentence = data.get('sentence', data.get('dialogue', data.get('text', '')))
        if not sentence.strip():
            logger.warning("Listening exercise missing sentence")
            return None

        # Extract words if not provided
        words = data.get('words', data.get('tokens', sentence.split()))

        repaired_data = {
            'id': data.get('id', f'listening_{hash(str(data))}'),
            'type': 'listening_mimic',
            'prompt': data.get('prompt', 'Listen and repeat'),
            'skill': normalize_skill(data.get('skill'), 'pronunciation'),
            'difficulty': data.get('difficulty', 1),
            'sentence': sentence,
            'correctPronunciation': data.get('correctPronunciation', data.get('correct_pronunciation', '')),
            'romaji': data.get('romaji'),
            'english': data.get('english'),
            'focus': data.get('focus'),
            'correctAnswer': data.get('correctAnswer', data.get('correct_answer', grading_value(data, 'correctAnswer', sentence))),
            'tip': data.get('tip', grading_value(data, 'tip', ''))
        }

        return ListeningMimicExercise(**repaired_data)
    except Exception as e:
        logger.error(f"Failed to repair Listening: {e}")
        return None


def repair_fill_blank_exercise(data: Dict[str, Any]) -> Optional[FillBlankExercise]:
    """Repair fill blank exercise"""
    try:
        sentence = data.get('sentence', '')
        if '_____' not in sentence:
            # Try to add blank marker
            words = sentence.split()
            if len(words) > 2:
                words[len(words)//2] = '_____'
                sentence = ' '.join(words)
            else:
                sentence = f"{sentence} _____"

        repaired_data = {
            'id': data.get('id', f'fill_blank_{hash(str(data))}'),
            'type': 'fill_blank',
            'prompt': data.get('prompt', 'Fill in the blank'),
            'skill': normalize_skill(data.get('skill'), 'vocabulary'),
            'difficulty': data.get('difficulty', 1),
            'sentence': sentence,
            'correct_answer': data.get('correctAnswer', data.get('correct_answer', grading_value(data, 'correctAnswer', ''))),
            'acceptedVariants': data.get('acceptedVariants', data.get('accepted_variants', grading_value(data, 'acceptedVariants', []))),
            'tip': data.get('tip', grading_value(data, 'tip', ''))
        }

        return FillBlankExercise(**repaired_data)
    except Exception as e:
        logger.error(f"Failed to repair Fill Blank: {e}")
        return None


def repair_checkpoint_exercise(data: Dict[str, Any]) -> Optional[CheckpointExercise]:
    """Repair checkpoint exercise"""
    try:
        repaired_data = {
            'id': data.get('id', f'checkpoint_{hash(str(data))}'),
            'type': 'checkpoint',
            'prompt': data.get('prompt', 'Complete the checkpoint'),
            'skill': normalize_skill(data.get('skill'), 'reading'),
            'difficulty': data.get('difficulty', 3),
            'title': data.get('title', 'Checkpoint'),
            'description': data.get('description', ''),
            'subTasks': data.get('subTasks', data.get('sub_tasks', [])),
            'correct_answer': data.get('correctAnswer', data.get('correct_answer', grading_value(data, 'correctAnswer', ''))),
            'tip': data.get('tip', grading_value(data, 'tip', ''))
        }

        return CheckpointExercise(**repaired_data)
    except Exception as e:
        logger.error(f"Failed to repair Checkpoint: {e}")
        return None


def repair_lesson_json(raw_json: str) -> Dict[str, Any]:
    """
    Repair malformed JSON from LLM output.
    Uses multiple strategies to extract valid JSON.
    """
    logger.debug(f"Attempting to repair JSON (length: {len(raw_json)})")
    
    # Strategy 0: Strip markdown code blocks (Gemini wraps JSON in ```json...```)
    if "```" in raw_json:
        logger.debug("Detecting markdown code block, attempting to extract JSON")
        # Find json/JSON block
        for marker in ["```json", "```JSON", "```"]:
            if marker in raw_json:
                try:
                    start_idx = raw_json.find(marker) + len(marker)
                    end_idx = raw_json.rfind("```")
                    if end_idx > start_idx:
                        candidate = raw_json[start_idx:end_idx].strip()
                        logger.debug(f"Extracted from markdown block")
                        result = json.loads(candidate)
                        logger.debug("Successfully parsed JSON from markdown")
                        return result
                except json.JSONDecodeError as e:
                    logger.debug(f"Markdown extraction failed: {e}")
    
    try:
        # Try direct parsing first
        result = json.loads(raw_json)
        logger.debug("Successfully parsed JSON on first try")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"Direct parsing failed: {e}")
        pass

    # Strategy 1: Find first { and last }
    start_idx = raw_json.find('{')
    end_idx = raw_json.rfind('}') + 1

    if start_idx >= 0 and end_idx > start_idx:
        try:
            candidate = raw_json[start_idx:end_idx]
            logger.debug(f"Trying Strategy 1: Extract JSON from position {start_idx} to {end_idx}")
            result = json.loads(candidate)
            logger.debug("Strategy 1 succeeded")
            return result
        except json.JSONDecodeError as e:
            logger.debug(f"Strategy 1 failed: {e}")
            pass

    # Strategy 2: Brace counting
    brace_count = 0
    start_pos = -1
    for i, char in enumerate(raw_json):
        if char == '{':
            if start_pos == -1:
                start_pos = i
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and start_pos != -1:
                try:
                    candidate = raw_json[start_pos:i+1]
                    logger.debug(f"Trying Strategy 2: Brace counting from {start_pos} to {i+1}")
                    result = json.loads(candidate)
                    logger.debug("Strategy 2 succeeded")
                    return result
                except json.JSONDecodeError as e:
                    logger.debug(f"Strategy 2 attempt failed: {e}")
                    start_pos = -1

    # Strategy 3: Try to fix common issues
    try:
        logger.debug("Trying Strategy 3: Fix common JSON issues")
        # Remove control characters
        fixed = raw_json.encode('utf-8', errors='ignore').decode('utf-8')
        # Try parsing
        result = json.loads(fixed)
        logger.debug("Strategy 3 succeeded")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"Strategy 3 failed: {e}")
        pass

    # Strategy 4: Add missing closing braces (last resort)
    try:
        logger.debug("Trying Strategy 4: Add missing closing braces")
        candidate = raw_json + '}' * 20  # Add more closing braces
        result = json.loads(candidate)
        logger.debug("Strategy 4 succeeded")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"Strategy 4 failed: {e}")
        pass

    logger.error(f"Could not repair JSON. Input sample: {raw_json[:200]}...")
    raise ValueError("Could not repair JSON")


def validate_and_repair_lesson(lesson_data: Dict[str, Any], mode: str = "learning_path") -> Dict[str, Any]:
    """
    Validate and repair a complete lesson.
    Returns repaired lesson data or raises exception.
    """
    # Handle case where JSON is a list (Gemini sometimes returns array)
    if isinstance(lesson_data, list):
        if len(lesson_data) > 0:
            lesson_data = lesson_data[0]  # Take first item
        else:
            raise ValueError("Cannot repair empty list")
    
    # Handle placement_test mode which has different structure
    if mode == "placement_test":
        # Generate unique IDs for the session
        import uuid
        from datetime import datetime
        
        session_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        user_id = f"user_{uuid.uuid4().hex[:8]}"
        
        # Extract or use defaults for placement test fields
        target_lang = lesson_data.get("targetLang") or lesson_data.get("target_lang") or "Unknown"
        native_lang = lesson_data.get("nativeLang") or lesson_data.get("native_lang") or "English"
        max_questions = lesson_data.get("maxQuestions") or lesson_data.get("max_questions") or 10
        time_limit = lesson_data.get("timeLimitSeconds") or lesson_data.get("time_limit_seconds") or 300
        
        # Get questions/exercises from the response
        questions_data = lesson_data.get("questions", []) or lesson_data.get("exercises", [])
        
        # Valid skill values enum
        VALID_SKILLS = ["vocabulary", "grammar", "translation", "pronunciation", "listening", "reading", "writing"]
        
        # Convert to PlacementTestQuestion format with heavy repair
        questions = []
        for i, q in enumerate(questions_data[:max_questions], 1):
            # Handle both exercise and question formats
            if isinstance(q, dict):
                question_id = q.get("id") or q.get("testId") or f"q_{i}"
                question_text = q.get("question") or q.get("prompt") or ""
                choices = q.get("choices") or q.get("options") or ["Option A", "Option B", "Option C", "Option D"]
                
                # Ensure choices is a list
                if not isinstance(choices, list):
                    choices = list(choices) if hasattr(choices, '__iter__') else ["Option A", "Option B", "Option C", "Option D"]
                
                correct_index = q.get("correctChoiceIndex") or q.get("correct_choice_index") or q.get("correctIndex") or 0
                
                # Ensure exactly 4 choices
                while len(choices) < 4:
                    choices.append(f"Option {chr(65 + len(choices))}")
                choices = choices[:4]
                
                # Ensure correctIndex is valid (0-3)
                if not isinstance(correct_index, int) or correct_index < 0 or correct_index >= len(choices):
                    correct_index = 0
                
                # Get correct answer - fallback to choice at correctIndex if not provided
                correct_answer = q.get("correctAnswer") or q.get("correct_answer")
                if not correct_answer:
                    correct_answer = choices[correct_index]
                
                # Fix skill - map invalid values to valid ones
                skill = q.get("skill") or "vocabulary"
                if skill not in VALID_SKILLS:
                    # Try to map common variations
                    skill_map = {
                        "readingcomprehension": "reading",
                        "readingcomprehensive": "reading",
                        "listeningcomprehension": "listening",
                        "pronuncation": "pronunciation",
                        "vocabulaire": "vocabulary",
                        "grammaaire": "grammar",
                        "traduction": "translation"
                    }
                    skill = skill_map.get(skill.lower(), "vocabulary")
                
                placement_question = {
                    "id": question_id,
                    "type": "mcq",
                    "cefrLevel": q.get("cefrLevel") or q.get("cefr_level") or "B1",
                    "skill": skill,
                    "difficulty": q.get("difficulty") or (i % 3 + 1),
                    "question": question_text,
                    "choices": choices,
                    "correctChoiceIndex": correct_index,
                    "correctAnswer": str(correct_answer),
                    "discriminationPower": float(q.get("discriminationPower") or q.get("discrimination_power") or 0.5),
                    "timeEstimateSeconds": int(q.get("timeEstimateSeconds") or q.get("time_estimate_seconds") or 30)
                }
                questions.append(placement_question)
        
        # Ensure we have at least 10 questions
        while len(questions) < 10:
            q_num = len(questions) + 1
            placeholder_question = {
                "id": f"q_{q_num}",
                "type": "mcq",
                "cefrLevel": "B1",
                "skill": "vocabulary",
                "difficulty": q_num % 3 + 1,
                "question": f"What is the correct answer for question {q_num}?",
                "choices": ["Option A", "Option B", "Option C", "Option D"],
                "correctChoiceIndex": 0,
                "correctAnswer": "Option A",
                "discriminationPower": 0.5,
                "timeEstimateSeconds": 30
            }
            questions.append(placeholder_question)
        
        # Trim to maxQuestions if needed
        questions = questions[:max_questions]
        
        # Create the final PlacementTest structure
        placement_test_data = {
            "testSessionId": session_id,
            "userId": user_id,
            "targetLang": target_lang,
            "nativeLang": native_lang,
            "maxQuestions": len(questions),
            "timeLimitSeconds": time_limit,
            "questions": questions,
            "adaptiveRules": {
                "startLevel": "B1",
                "difficultyAdjustment": "dynamic"
            }
        }
        
        # Validate against PlacementTest model
        try:
            lesson = PlacementTest(**placement_test_data)
            return lesson.model_dump(by_alias=True)
        except Exception as e:
            logger.error(f"Failed to create PlacementTest: {e}")
            raise
    
    # Handle learning_path and ad_hoc_lesson modes
    try:
        exercises_data = lesson_data.get('exercises', [])
        repaired_exercises = []

        for ex_data in exercises_data:
            repaired_ex = repair_exercise(ex_data)
            if repaired_ex:
                repaired_exercises.append(repaired_ex.model_dump(by_alias=True))
            else:
                logger.warning(f"Could not repair exercise: {ex_data.get('id')}")
        
        # Ensure we have at least 10 exercises (pad if needed)
        if len(repaired_exercises) < 10:
            logger.warning(f"Only {len(repaired_exercises)} exercises, padding to 10")
            while len(repaired_exercises) < 10:
                # Create a stub exercise to pad
                ex_id = f"task_{len(repaired_exercises) + 1}"
                stub_exercise = {
                    "id": ex_id,
                    "type": "mcq",
                    "prompt": "Choose the correct answer",
                    "skill": "vocabulary",
                    "difficulty": 1,
                    "question": "Select the correct option",
                    "choices": ["Option A", "Option B", "Option C", "Option D"],
                    "correctChoiceIndex": 0,
                    "correct_answer": "Option A",
                    "tip": "This is a placeholder exercise"
                }
                repaired_exercises.append(stub_exercise)
                logger.warning(f"Added stub exercise {ex_id}")
        
        # Trim to exactly 10 if more
        if len(repaired_exercises) > 10:
            logger.warning(f"Trimming {len(repaired_exercises)} exercises to 10")
            repaired_exercises = repaired_exercises[:10]

        lesson_data['exercises'] = repaired_exercises

        if mode == "learning_path" and not (lesson_data.get("lessonId") or lesson_data.get("lesson_id")):
            seed = "|".join(
                str(lesson_data.get(key, ""))
                for key in ("targetLang", "target_lang", "nativeLang", "native_lang", "level", "topic")
            )
            digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
            lesson_data["lessonId"] = f"lesson_{digest}"

        # For ad_hoc lessons, ensure lessonLength matches exercise count
        if mode in ("ad_hoc", "ad_hoc_lesson"):
            if 'lessonLength' not in lesson_data and 'lesson_length' not in lesson_data:
                lesson_data['lessonLength'] = len(repaired_exercises)

        # Validate against mode-specific schema
        if mode == "learning_path":
            lesson = LearningPathLesson(**lesson_data)
        elif mode in ("ad_hoc", "ad_hoc_lesson"):
            lesson = AdHocLesson(**lesson_data)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        return lesson.model_dump(by_alias=True)

    except Exception as e:
        logger.error(f"Lesson validation/repair failed: {e}")
        raise

