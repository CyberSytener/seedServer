"""Model catalog helpers — extracted from main.py."""
from __future__ import annotations

from app.models.api import ModelCatalogItem, ModelPricingHint
from app.services.llm import DEFAULT_MODEL_PRICING
from app.settings import Settings


def _provider_for_model(model_id: str) -> str:
    model_lower = model_id.lower()
    if model_lower.startswith("gemini"):
        return "gemini"
    if model_lower.startswith("gpt"):
        return "openai"
    return "other"


def _tier_for_model(model_id: str) -> str:
    model_lower = model_id.lower()
    if "pro" in model_lower:
        return "pro"
    if "flash" in model_lower or "mini" in model_lower:
        return "fast"
    return "standard"


def _label_for_model(model_id: str) -> str:
    return model_id.replace("-", " ").title()


def _is_model_available(provider: str, settings: Settings) -> bool:
    if provider == "gemini":
        return bool(settings.enable_gemini and settings.gemini_api_key)
    if provider == "openai":
        return bool(settings.enable_openai and settings.openai_api_key)
    if provider == "stub":
        return bool(settings.enable_stub)
    return True


def _capabilities_for_model(model_id: str, settings: Settings) -> list[str]:
    capabilities: list[str] = []
    if model_id in {settings.gemini_model_fast, settings.openai_model_fast}:
        capabilities.append("fast")
    if model_id in {settings.gemini_model_batch, settings.openai_model_batch}:
        capabilities.append("batch")

    model_lower = model_id.lower()
    if "pro" in model_lower:
        capabilities.append("reasoning")
    if "flash" in model_lower or "mini" in model_lower:
        capabilities.append("low_latency")

    if not capabilities:
        capabilities.append("general")
    return capabilities


def build_models_catalog(settings: Settings) -> list[ModelCatalogItem]:
    """Build the full model catalog advertised via ``/v1/models``."""
    configured_models = [
        settings.gemini_model_fast,
        settings.gemini_model_batch,
        settings.openai_model_fast,
        settings.openai_model_batch,
    ]
    seen: set[str] = set()
    model_ids: list[str] = []
    for model_id in [*DEFAULT_MODEL_PRICING.keys(), *configured_models]:
        normalized = str(model_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        model_ids.append(normalized)

    catalog: list[ModelCatalogItem] = []
    for model_id in model_ids:
        provider = _provider_for_model(model_id)
        pricing = DEFAULT_MODEL_PRICING.get(
            model_id,
            {
                "input_per_1k_tokens_usd": 0.0,
                "output_per_1k_tokens_usd": 0.0,
                "credit_multiplier": 1.0,
            },
        )
        catalog.append(
            ModelCatalogItem(
                provider=provider,
                id=model_id,
                label=_label_for_model(model_id),
                tier=_tier_for_model(model_id),
                capabilities=_capabilities_for_model(model_id, settings),
                available=_is_model_available(provider, settings),
                pricing=ModelPricingHint(
                    inputPer1kTokensUsd=float(pricing.get("input_per_1k_tokens_usd", 0.0)),
                    outputPer1kTokensUsd=float(pricing.get("output_per_1k_tokens_usd", 0.0)),
                    creditMultiplier=float(pricing.get("credit_multiplier", 1.0)),
                ),
            )
        )

    return catalog
