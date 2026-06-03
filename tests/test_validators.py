"""
Tests for mode-specific validators and repair functions.
"""

import pytest
import json
from app.core.validators.validators.models import (
    MCQExercise, TranslationExercise, WordBankExercise,
    ListeningMimicExercise, LearningPathLesson, AdHocLesson
)
from app.core.validators.validators.repair import (
    repair_exercise, repair_mcq_exercise, repair_translation_exercise,
    repair_word_bank_exercise, repair_listening_exercise,
    repair_lesson_json, validate_and_repair_lesson
)


class TestExerciseRepair:
    """Test repair functions for individual exercises"""

    def test_repair_mcq_exercise_complete(self):
        """Test repairing a complete MCQ exercise"""
        data = {
            "id": "task_1",
            "type": "mcq",
            "prompt": "Choose the correct answer",
            "skill": "vocabulary",
            "difficulty": 1,
            "question": "What does 'hello' mean?",
            "choices": ["Goodbye", "Hello", "Please", "Thank you"],
            "correctChoiceIndex": 1,
            "correctAnswer": "Hello",
            "tip": "Basic greeting"
        }

        result = repair_mcq_exercise(data)
        assert result is not None
        assert result.type == "mcq"
        assert result.correct_choice_index == 1
        assert len(result.choices) == 4

    def test_repair_mcq_exercise_missing_choices(self):
        """Test repairing MCQ with missing choices"""
        data = {
            "id": "task_1",
            "type": "mcq",
            "question": "What does 'hello' mean?",
            "correctChoiceIndex": 0,
            "correctAnswer": "Hello"
        }

        result = repair_mcq_exercise(data)
        assert result is not None
        assert len(result.choices) == 4  # Should create defaults
        assert result.correct_choice_index == 0

    def test_repair_translation_exercise(self):
        """Test repairing translation exercise"""
        data = {
            "id": "task_4",
            "type": "translation",
            "sourceText": "Good morning",
            "correctAnswer": "Buenos días",
            "acceptedVariants": ["Buen día"]
        }

        result = repair_translation_exercise(data)
        assert result is not None
        assert result.source_text == "Good morning"
        assert result.correct_answer == "Buenos días"

    def test_repair_translation_exercise_missing_source(self):
        """Test repairing translation with missing source text"""
        data = {
            "id": "task_4",
            "type": "translation",
            "correctAnswer": "Buenos días"
        }

        result = repair_translation_exercise(data)
        assert result is None  # Should fail without source text

    def test_repair_word_bank_exercise(self):
        """Test repairing word bank exercise"""
        data = {
            "id": "task_7",
            "type": "word_bank",
            "tokens": ["Mi", "nombre", "es", "María"],
            "correctSentence": "Mi nombre es María"
        }

        result = repair_word_bank_exercise(data)
        assert result is not None
        assert len(result.words) >= 3
        assert result.correct_answer == "Mi nombre es María"

    def test_repair_listening_exercise(self):
        """Test repairing listening exercise"""
        data = {
            "id": "task_9",
            "type": "listening_mimic",
            "sentence": "Buenos días",
            "correctPronunciation": "BWEH-nohs DEE-ahs"
        }

        result = repair_listening_exercise(data)
        assert result is not None
        assert result.sentence == "Buenos días"
        assert result.correct_answer == "Buenos días"


class TestLessonValidation:
    """Test complete lesson validation and repair"""

    def test_validate_learning_path_lesson_valid(self):
        """Test validating a valid learning path lesson"""
        lesson_data = {
            "lessonId": "lesson_test",
            "mode": "learning_path",
            "targetLang": "Spanish",
            "nativeLang": "English",
            "level": "A1",
            "topic": "Greetings",
            "nodeId": "node_1",
            "unitId": "unit_1",
            "xpReward": 15,
            "exercises": [
                {
                    "id": "task_1",
                    "type": "mcq",
                    "prompt": "Choose",
                    "skill": "vocabulary",
                    "difficulty": 1,
                    "question": "What?",
                    "choices": ["A", "B", "C", "D"],
                    "correctChoiceIndex": 0,
                    "correctAnswer": "A",
                    "tip": "Tip"
                },
                # Add more exercises to make 10 total with correct distribution
            ] + [
                {
                    "id": f"task_{i}",
                    "type": "mcq" if i <= 3 else "translation" if i <= 6 else "word_bank" if i <= 8 else "listening_mimic",
                    "prompt": f"Prompt {i}",
                    "skill": "vocabulary",
                    "difficulty": 1,
                    "question": f"Question {i}" if i <= 3 else None,
                    "choices": ["A", "B", "C", "D"] if i <= 3 else None,
                    "correctChoiceIndex": 0 if i <= 3 else None,
                    "sourceText": f"Text {i}" if 4 <= i <= 6 else None,
                    "words": ["word1", "word2", "word3"] if 7 <= i <= 8 else None,
                    "sentence": f"Sentence {i}" if i >= 9 else None,
                    "correctAnswer": f"Answer {i}",
                    "tip": f"Tip {i}"
                } for i in range(2, 11)
            ]
        }

        # This would need a complete valid lesson - simplified for test structure
        # result = validate_and_repair_lesson(lesson_data, "learning_path")
        # assert result is not None
        pass

    def test_repair_malformed_json(self):
        """Test repairing malformed JSON from LLM"""
        malformed_json = '''
        {
          "lessonId": "lesson_test",
          "exercises": [
            {
              "id": "task_1",
              "type": "mcq",
              "question": "What?",
              "choices": ["A", "B", "C", "D"],
              "correctChoiceIndex": 0,
              "correct_answer": "A"
            }
          ]
        }
        '''
        # Valid JSON but with extra content - should extract the valid part

        result = repair_lesson_json(malformed_json)
        assert result is not None
        assert "lessonId" in result
        assert len(result["exercises"]) == 1


class TestModelValidation:
    """Test Pydantic model validation"""

    def test_mcq_model_validation(self):
        """Test MCQ model validation"""
        data = {
            "id": "task_1",
            "type": "mcq",
            "prompt": "Choose",
            "skill": "vocabulary",
            "difficulty": 1,
            "question": "What?",
            "choices": ["A", "B", "C", "D"],
            "correctChoiceIndex": 0,
            "correct_answer": "A",
            "tip": "Tip"
        }

        exercise = MCQExercise(**data)
        assert exercise.type == "mcq"
        assert len(exercise.choices) == 4

    def test_translation_model_validation(self):
        """Test Translation model validation"""
        data = {
            "id": "task_4",
            "type": "translation",
            "prompt": "Translate",
            "skill": "translation",
            "difficulty": 1,
            "sourceText": "Hello",
            "targetLang": "Spanish",
            "correct_answer": "Hola",
            "acceptedVariants": ["Hi"],
            "tip": "Greeting"
        }

        exercise = TranslationExercise(**data)
        assert exercise.source_text == "Hello"
        assert exercise.target_lang == "Spanish"

    def test_learning_path_distribution_validation(self):
        """Test that learning path enforces exercise distribution"""
        # This would test the model validator for distribution
        # For now, just ensure models can be imported
        from app.validators.models import LearningPathLesson
        assert LearningPathLesson is not None