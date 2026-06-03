from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.models.api import DiagnosticGenerateRequest, LessonGenerateRequest, Task
from app.services.diagnostic.engine import generate_diagnostic_items
from app.services.lesson.engine import generate_lesson, grade_submission


def _build_lesson_payload() -> dict:
    return {
        "lessonId": "lesson_fallback_1",
        "mode": "mixed",
        "targetLang": "Spanish",
        "nativeLang": "English",
        "level": "beginner",
        "topic": "greetings",
        "title": "Greeting Basics",
        "tasks": [
            {
                "id": "t1",
                "type": "mcq",
                "prompt": "Choose the Spanish word for hello",
                "skill": "vocabulary",
                "difficulty": 1,
                "content": {
                    "question": "Which means hello?",
                    "choices": ["Hola", "Adiós", "Gracias", "Por favor"],
                    "sourceText": "hello",
                },
                "grading": {
                    "correctChoiceIndex": 0,
                    "correctAnswer": "Hola",
                    "acceptedVariants": [],
                    "partialCreditKeywords": [],
                    "tip": "Use basic greetings.",
                },
            },
            {
                "id": "t2",
                "type": "translate",
                "prompt": "Translate: Good morning",
                "skill": "translation",
                "difficulty": 1,
                "content": {
                    "sourceText": "Good morning",
                    "targetLang": "Spanish",
                },
                "grading": {
                    "correctAnswer": "Buenos días",
                    "acceptedVariants": ["Buen día"],
                    "partialCreditKeywords": [],
                    "tip": "Think of common morning greeting.",
                },
            },
            {
                "id": "t3",
                "type": "fill_blank",
                "prompt": "Complete the greeting",
                "skill": "grammar",
                "difficulty": 1,
                "content": {
                    "sentenceWithBlank": "_____ días",
                },
                "grading": {
                    "correctAnswer": "Buenos",
                    "acceptedVariants": ["Buen"],
                    "partialCreditKeywords": [],
                    "tip": "Plural adjective form.",
                },
            },
        ],
    }


def _build_diagnostic_payload() -> dict:
    return {
        "items": [
            {
                "id": "d1",
                "taskType": "mcq",
                "prompt": "Choose the correct translation for 'book'",
                "context": {},
                "choices": ["libro", "mesa", "agua", "casa"],
                "answer": {"accepted": ["libro"], "normalize": "lower_trim"},
                "distractorsReason": [
                    {"choice": "mesa", "reasonTag": "semantic_neighbor"},
                    {"choice": "agua", "reasonTag": "topic_mismatch"},
                    {"choice": "casa", "reasonTag": "frequent_confusion"},
                ],
                "tags": {
                    "skill": "vocabulary",
                    "subskill": "nouns",
                    "topic": "basics",
                    "difficulty": 1.0,
                    "taskType": "mcq",
                    "cefrBand": "A1",
                    "languagePair": "English->Spanish",
                },
            }
        ]
    }


def test_lesson_generate_falls_back_when_prompt_sources_missing():
    req = LessonGenerateRequest(
        mode="mixed",
        targetLang="Spanish",
        nativeLang="English",
        level="beginner",
        lessonLength=3,
        topic="greetings",
    )

    with (
        patch("app.services.lesson.engine.get_prompt_for_test", side_effect=RuntimeError("missing prompt files")),
        patch("app.services.lesson.engine.GENERATOR_PROMPT", ""),
        patch("app.services.lesson.engine.GENERATOR_PROMPT_COMPACT", ""),
        patch("app.services.lesson.engine.execute_llm_request", return_value=json.dumps(_build_lesson_payload())),
    ):
        lesson = generate_lesson(
            req=req,
            persona_prompt="You are encouraging.",
            provider="stub",
            model="stub",
            user_id="u_prompt_fallback",
        )

    assert lesson.lesson_id == "lesson_fallback_1"
    assert len(lesson.tasks) == 3


def test_lesson_submit_grading_falls_back_when_grader_prompt_missing():
    task = Task.model_validate(
        {
            "id": "task_translate_1",
            "type": "translate",
            "prompt": "Translate: Hello",
            "skill": "vocabulary",
            "difficulty": 1,
            "content": {"sourceText": "Hello", "targetLang": "Spanish"},
            "grading": {
                "correctAnswer": "Hola",
                "acceptedVariants": ["¡Hola!"],
                "partialCreditKeywords": [],
                "tip": "Use a simple greeting.",
            },
        }
    )

    with (
        patch("app.services.lesson.engine.GRADER_PROMPT", ""),
        patch(
            "app.services.lesson.engine.execute_llm_request",
            return_value=json.dumps(
                {
                    "taskId": "task_translate_1",
                    "correct": True,
                    "score": 1.0,
                    "feedback": "Great answer!",
                    "correctAnswer": None,
                }
            ),
        ) as llm_mock,
    ):
        grade = grade_submission(
            task=task,
            user_answer="Hola",
            persona_prompt="Keep it positive.",
            provider="stub",
            model="stub",
        )

    assert grade.correct is True
    assert grade.score == 1.0
    assert "GRADING MODE" in llm_mock.call_args.kwargs["system_prompt"]


def test_diagnostic_generation_falls_back_when_prompt_files_missing(tmp_path: Path):
    request = DiagnosticGenerateRequest(
        nativeLang="English",
        targetLang="Spanish",
        blueprint=[
            {
                "skill": "vocabulary",
                "subskill": "nouns",
                "topic": "basics",
                "difficulty": 1.0,
                "taskType": "mcq",
                "cefrBand": "A1",
            }
        ],
        personaId="default",
    )

    missing_base = tmp_path / "missing" / "diagnostic_generator.md"
    missing_compact = tmp_path / "missing" / "diagnostic_generator_compact.md"
    missing_test = tmp_path / "missing" / "test" / "diagnostic_generator.md"

    with (
        patch("app.services.diagnostic.engine.DIAGNOSTIC_PROMPT_FILE", missing_base),
        patch("app.services.diagnostic.engine.DIAGNOSTIC_PROMPT_COMPACT_FILE", missing_compact),
        patch("app.services.diagnostic.engine.DIAGNOSTIC_PROMPT_TEST_FILE", missing_test),
        patch("app.services.diagnostic.engine.execute_llm_request", return_value=json.dumps(_build_diagnostic_payload())),
    ):
        response = generate_diagnostic_items(
            request=request,
            user_id="u_diag_prompt_fallback",
            optimize_mode=False,
        )

    assert len(response.diagnostic_set.items) == 1
    assert response.diagnostic_set.items[0].task_type == "mcq"
