"""
Pydantic models and validators for different lesson modes.
Includes repair functions for common LLM output issues.
"""

from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum


class ExerciseType(str, Enum):
    mcq = "mcq"
    translation = "translation"
    word_bank = "word_bank"
    listening_mimic = "listening_mimic"
    fill_blank = "fill_blank"
    checkpoint = "checkpoint"


class SkillType(str, Enum):
    vocabulary = "vocabulary"
    grammar = "grammar"
    translation = "translation"
    pronunciation = "pronunciation"
    listening = "listening"
    reading = "reading"
    writing = "writing"


# Base exercise models
class BaseExercise(BaseModel):
    id: str
    type: ExerciseType
    prompt: str
    skill: SkillType
    difficulty: int = Field(ge=1, le=5)


class MCQExercise(BaseExercise):
    type: str = "mcq"
    question: str
    choices: List[str] = Field(min_length=4, max_length=4)
    correct_choice_index: int = Field(ge=0, le=3, alias="correctChoiceIndex")
    correct_answer: str
    tip: str = ""

    @field_validator('choices')
    @classmethod
    def validate_choices(cls, v):
        if len(v) != 4:
            raise ValueError('MCQ must have exactly 4 choices')
        return v


class TranslationExercise(BaseExercise):
    type: str = "translation"
    source_text: str = Field(alias="sourceText")
    target_lang: str = Field(alias="targetLang")
    correct_answer: str
    accepted_variants: List[str] = Field(default_factory=list, alias="acceptedVariants")
    tip: str = ""


class WordBankExercise(BaseExercise):
    type: str = "word_bank"
    words: List[str] = Field(min_length=3)
    sentence: str  # Target sentence to form
    correct_answer: str = Field(alias="correctAnswer")
    tip: str = ""


class ListeningMimicExercise(BaseExercise):
    type: str = "listening_mimic"
    sentence: str  # Dialogue line to pronounce
    correct_pronunciation: Optional[str] = Field(default=None, alias="correctPronunciation")
    romaji: Optional[str] = None
    english: Optional[str] = None
    focus: Optional[str] = None
    correct_answer: str = Field(alias="correctAnswer")
    tip: str = ""


class FillBlankExercise(BaseExercise):
    type: str = "fill_blank"
    sentence: str  # Sentence with _____ placeholder
    correct_answer: str
    accepted_variants: List[str] = Field(default_factory=list, alias="acceptedVariants")
    tip: str = ""

    @field_validator('sentence')
    @classmethod
    def validate_blank_marker(cls, v):
        if '_____' not in v:
            raise ValueError('Fill blank sentence must contain _____ marker')
        return v


class CheckpointExercise(BaseExercise):
    type: str = "checkpoint"
    title: str
    description: str
    sub_tasks: List[Dict[str, Any]] = Field(alias="subTasks")  # Complex multi-part task
    correct_answer: str
    tip: str = ""


# Union type for all exercises
Exercise = Union[
    MCQExercise,
    TranslationExercise,
    WordBankExercise,
    ListeningMimicExercise,
    FillBlankExercise,
    CheckpointExercise
]


# Mode-specific lesson models
class LearningPathLesson(BaseModel):
    lesson_id: str = Field(alias="lessonId")
    mode: str = "learning_path"
    target_lang: str = Field(alias="targetLang")
    native_lang: str = Field(alias="nativeLang")
    level: str
    topic: str
    node_id: Optional[str] = Field(default=None, alias="nodeId")
    unit_id: Optional[str] = Field(default=None, alias="unitId")
    xp_reward: int = Field(default=15, alias="xpReward")
    exercises: List[Exercise] = Field(min_length=10, max_length=10)

    @model_validator(mode='after')
    def validate_exercise_distribution(self):
        """Ensure correct exercise distribution for learning path"""
        exercises = self.exercises
        mcq_count = sum(1 for ex in exercises if ex.type == "mcq")
        translation_count = sum(1 for ex in exercises if ex.type == "translation")
        word_bank_count = sum(1 for ex in exercises if ex.type == "word_bank")
        listening_count = sum(1 for ex in exercises if ex.type == "listening_mimic")

        if not (mcq_count == 3 and translation_count == 3 and
                word_bank_count == 2 and listening_count == 2):
            raise ValueError(
                f"Learning Path requires exact distribution: 3 MCQ, 3 Translation, 2 Word Bank, 2 Listening. "
                f"Got: {mcq_count} MCQ, {translation_count} Translation, "
                f"{word_bank_count} Word Bank, {listening_count} Listening"
            )
        return self


class PlacementTestQuestion(BaseModel):
    id: str
    type: ExerciseType
    cefr_level: str = Field(alias="cefrLevel")
    skill: SkillType
    difficulty: int
    question: str
    choices: List[str] = Field(min_length=4, max_length=4)
    correct_choice_index: int = Field(ge=0, le=3, alias="correctChoiceIndex")
    correct_answer: str = Field(alias="correctAnswer")
    discrimination_power: float = Field(ge=0.0, le=1.0, alias="discriminationPower")
    time_estimate_seconds: int = Field(alias="timeEstimateSeconds")


class PlacementTest(BaseModel):
    test_session_id: str = Field(alias="testSessionId")
    user_id: str = Field(alias="userId")
    target_lang: str = Field(alias="targetLang")
    native_lang: str = Field(alias="nativeLang")
    max_questions: int = Field(alias="maxQuestions")
    time_limit_seconds: int = Field(alias="timeLimitSeconds")
    questions: List[PlacementTestQuestion]
    adaptive_rules: Dict[str, Any] = Field(default_factory=lambda: {"startLevel": "B1", "difficultyAdjustment": "dynamic"}, alias="adaptiveRules")


class AdHocLesson(BaseModel):
    lesson_id: str = Field(alias="lessonId")
    mode: str = "ad_hoc"
    target_lang: str = Field(alias="targetLang")
    native_lang: str = Field(alias="nativeLang")
    level: str
    topic: str
    lesson_length: int = Field(alias="lessonLength")
    exercises: List[Exercise]

    @model_validator(mode='after')
    def validate_exercise_count(self):
        if len(self.exercises) != self.lesson_length:
            raise ValueError(f"Expected {self.lesson_length} exercises, got {len(self.exercises)}")
        return self