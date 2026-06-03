from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class PipelineSettings:
    default_provider_fast: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_model_fast: str = "gemini-2.0-flash-lite"


def get_settings() -> PipelineSettings:
    return PipelineSettings(
        default_provider_fast=os.getenv("SEED_DEFAULT_PROVIDER_FAST"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        gemini_model_fast=os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-2.0-flash-lite",
    )
