"""
AI Pipeline - Orchestration Pattern для цепочки LLM моделей

Позволяет строить конвейеры вида:
User -> LLM (Architect) -> LLM (Content) -> LLM (Reviewer) -> User
"""

from .core import PipelineContext, PipelineStep, PipelineOrchestrator
from .steps import (
    LessonPlannerStep,
    LessonContentStep,
    LessonValidatorStep,
    DiagnosticPlannerStep,
    DiagnosticGeneratorStep
)
from .runners import (
    run_lesson_generation_pipeline,
    run_diagnostic_generation_pipeline
)

__all__ = [
    "PipelineContext",
    "PipelineStep",
    "PipelineOrchestrator",
    "LessonPlannerStep",
    "LessonContentStep",
    "LessonValidatorStep",
    "DiagnosticPlannerStep",
    "DiagnosticGeneratorStep",
    "run_lesson_generation_pipeline",
    "run_diagnostic_generation_pipeline",
]
