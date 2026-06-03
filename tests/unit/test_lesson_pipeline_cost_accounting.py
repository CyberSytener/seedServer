from __future__ import annotations

import json
import sys
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.lesson.pipeline import generate_lesson_with_pipeline


def _lesson_content_json() -> str:
    exercises = []
    for index in range(1, 11):
        if index <= 3:
            exercises.append(
                {
                    "id": f"task_{index}",
                    "type": "mcq",
                    "prompt": f"MCQ prompt {index}",
                    "question": f"Question {index}",
                    "choices": ["a", "b", "c", "d"],
                    "correctChoiceIndex": 0,
                    "skill": "vocabulary",
                    "difficulty": 1,
                    "grading": {"correctAnswer": "a", "correctChoiceIndex": 0, "tip": "tip"},
                }
            )
        elif index <= 6:
            exercises.append(
                {
                    "id": f"task_{index}",
                    "type": "translation",
                    "prompt": f"Translate {index}",
                    "sourceText": "hello",
                    "skill": "translation",
                    "difficulty": 1,
                    "grading": {"correctAnswer": "hola", "acceptedVariants": ["hola"], "tip": "tip"},
                }
            )
        elif index <= 8:
            exercises.append(
                {
                    "id": f"task_{index}",
                    "type": "word_bank",
                    "prompt": f"Word bank {index}",
                    "tokens": ["yo", "soy", "estudiante"],
                    "correctSentence": "yo soy estudiante",
                    "skill": "word_order",
                    "difficulty": 1,
                    "grading": {"correctAnswer": "yo soy estudiante", "tip": "tip"},
                }
            )
        else:
            exercises.append(
                {
                    "id": f"task_{index}",
                    "type": "listening_mimic",
                    "prompt": f"Listening {index}",
                    "words": ["buenos", "dias"],
                    "dialogue": "Buenos días",
                    "skill": "listening",
                    "difficulty": 1,
                    "grading": {"correctAnswer": "Buenos días", "tip": "tip"},
                }
            )

    payload = {
        "title": "Pipeline Cost Lesson",
        "level": "A1",
        "targetLang": "Spanish",
        "nativeLang": "English",
        "topic": "Greetings",
        "exercises": exercises,
    }
    return json.dumps(payload)


class _FakeLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "lessonTitle": "Plan",
                        "learningObjectives": ["obj1", "obj2", "obj3"],
                        "grammar_points": ["point1", "point2"],
                        "vocabulary_count": 10,
                        "dialogue_scenes": ["scene1", "scene2"],
                        "task_descriptions": [f"Task {idx}" for idx in range(1, 11)],
                        "exercises_plan": [f"e{idx}" for idx in range(1, 11)],
                    }
                ),
                provider="gemini",
                model="gemini-2.0-flash",
                tokens_in=80,
                tokens_out=120,
            )
        if self.calls == 2:
            return SimpleNamespace(
                text=_lesson_content_json(),
                provider="gemini",
                model="gemini-2.5-pro",
                tokens_in=250,
                tokens_out=420,
            )
        return SimpleNamespace(
            text=json.dumps(
                {
                    "valid": True,
                    "exercise_diversity_compliant": True,
                    "cefr_appropriate": True,
                    "issues": [],
                    "score": 93,
                    "recommendation": "APPROVE",
                }
            ),
            provider="gemini",
            model="gemini-2.0-flash",
            tokens_in=100,
            tokens_out=60,
        )


@pytest.mark.asyncio
async def test_lesson_pipeline_returns_aggregated_cost_summary():
    fake_client = _FakeLLMClient()
    prompts_pkg = ModuleType("app.services.pipeline.prompts")
    learning_path_prompts = ModuleType("app.services.pipeline.prompts.learning_path")
    learning_path_prompts.LEARNING_PATH_CONTENT_CREATOR_PROMPT = "{target_lang} {native_lang} {cefr_level} {topic}"
    learning_path_prompts.LEARNING_PATH_VALIDATOR_PROMPT = "{lesson_json}"
    validators_pkg = ModuleType("app.services.pipeline.validators")
    validators_repair = ModuleType("app.services.pipeline.validators.repair")
    validators_repair.repair_lesson_json = lambda raw: json.loads(raw)
    validators_repair.validate_and_repair_lesson = lambda payload, mode: payload
    sys.modules["app.services.pipeline.prompts"] = prompts_pkg
    sys.modules["app.services.pipeline.prompts.learning_path"] = learning_path_prompts
    sys.modules["app.services.pipeline.validators"] = validators_pkg
    sys.modules["app.services.pipeline.validators.repair"] = validators_repair

    with (
        patch("app.services.pipeline.pipeline.steps.get_llm_client", return_value=fake_client),
        patch("app.services.pipeline.pipeline.steps.BillingMetrics.record_credit_ledger_event") as billing_mock,
    ):
        result = await generate_lesson_with_pipeline(
            target_lang="Spanish",
            native_lang="English",
            cefr_level="A1",
            topic="Greetings",
            trace_id="trace_lesson_1",
            session_id="session_lesson_1",
            job_id="job_lesson_1",
            user_id="u_pipeline_cost",
        )

    assert result["success"] is True
    cost_summary = result["cost_summary"]
    assert cost_summary["total_cost_usd"] > 0.0
    assert cost_summary["total_credits_charged"] > 0
    assert len(cost_summary["cost_breakdown"]) == 3
    assert [item["stage"] for item in cost_summary["cost_breakdown"]] == ["candidate", "validator", "final"]
    assert billing_mock.call_count == 3

    sys.modules.pop("app.services.pipeline.validators.repair", None)
    sys.modules.pop("app.services.pipeline.validators", None)
    sys.modules.pop("app.services.pipeline.prompts.learning_path", None)
    sys.modules.pop("app.services.pipeline.prompts", None)
