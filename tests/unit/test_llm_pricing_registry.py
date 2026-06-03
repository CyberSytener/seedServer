from __future__ import annotations

from app.core.llm.pricing import resolve_pricing_metadata


def test_pricing_registry_resolves_known_provider_model():
    meta = resolve_pricing_metadata(provider="gemini", model="gemini-2.0-flash")

    assert meta["provider"] == "gemini"
    assert meta["model"] == "gemini-2.0-flash"
    assert str(meta.get("pricing_version") or "").strip()
    rates = meta.get("rates") or {}
    assert float(rates.get("input_per_1k_tokens_usd") or 0.0) > 0.0
    assert float(rates.get("output_per_1k_tokens_usd") or 0.0) > 0.0
    assert float(rates.get("credit_multiplier") or 0.0) >= 0.1


def test_pricing_registry_falls_back_to_defaults_for_unknown_model():
    meta = resolve_pricing_metadata(provider="openai", model="unknown-model-xyz")
    rates = meta.get("rates") or {}

    assert meta["provider"] == "openai"
    assert meta["model"] == "unknown-model-xyz"
    assert float(rates.get("input_per_1k_tokens_usd") or 0.0) == 0.0
    assert float(rates.get("output_per_1k_tokens_usd") or 0.0) == 0.0
    assert float(rates.get("credit_multiplier") or 0.0) >= 0.1
