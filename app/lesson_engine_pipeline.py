from __future__ import annotations

from typing import Any, Dict

from app.services.lesson.pipeline import (
    convert_pipeline_lesson_to_model,
    generate_lesson_from_pipeline,
)


async def generate_lesson_from_pipeline_async(**kwargs: Any) -> Dict[str, Any]:
    return await generate_lesson_from_pipeline(**kwargs)


__all__ = [
    "generate_lesson_from_pipeline_async",
    "convert_pipeline_lesson_to_model",
]
