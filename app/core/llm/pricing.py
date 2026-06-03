from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

DEFAULT_PRICING_VERSION = "pricing.v1"

DEFAULT_PRICING_CATALOG: Dict[str, Any] = {
    "pricing_version": DEFAULT_PRICING_VERSION,
    "providers": {
        "gemini": {
            "models": {
                "gemini-2.0-flash": {
                    "input_per_1k_tokens_usd": 0.000075,
                    "output_per_1k_tokens_usd": 0.00030,
                    "credit_multiplier": 1.0,
                },
                "gemini-2.5-pro": {
                    "input_per_1k_tokens_usd": 0.00125,
                    "output_per_1k_tokens_usd": 0.00500,
                    "credit_multiplier": 1.5,
                },
            }
        },
        "openai": {
            "models": {
                "gpt-4.1-mini": {
                    "input_per_1k_tokens_usd": 0.00015,
                    "output_per_1k_tokens_usd": 0.00060,
                    "credit_multiplier": 1.2,
                },
                "gpt-4.1": {
                    "input_per_1k_tokens_usd": 0.00100,
                    "output_per_1k_tokens_usd": 0.00300,
                    "credit_multiplier": 1.4,
                },
            }
        },
        "stub": {
            "models": {
                "stub": {
                    "input_per_1k_tokens_usd": 0.0,
                    "output_per_1k_tokens_usd": 0.0,
                    "credit_multiplier": 0.1,
                }
            }
        },
    },
    "defaults": {
        "input_per_1k_tokens_usd": 0.0,
        "output_per_1k_tokens_usd": 0.0,
        "credit_multiplier": 1.0,
    },
}


def _default_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "pricing_catalog.yaml"


def _normalize_rates(raw: Any) -> Dict[str, float]:
    if not isinstance(raw, dict):
        return {
            "input_per_1k_tokens_usd": 0.0,
            "output_per_1k_tokens_usd": 0.0,
            "credit_multiplier": 1.0,
        }

    return {
        "input_per_1k_tokens_usd": float(raw.get("input_per_1k_tokens_usd") or 0.0),
        "output_per_1k_tokens_usd": float(raw.get("output_per_1k_tokens_usd") or 0.0),
        "credit_multiplier": max(0.1, float(raw.get("credit_multiplier") or 1.0)),
    }


def _resolve_model_rates_from_catalog(
    *,
    provider: str,
    model: str,
    catalog: Dict[str, Any],
) -> Dict[str, Any]:
    provider_name = str(provider or "unknown").strip().lower() or "unknown"
    model_name = str(model or "").strip() or "unknown"

    providers = catalog.get("providers") if isinstance(catalog.get("providers"), dict) else {}
    provider_cfg = providers.get(provider_name) if isinstance(providers.get(provider_name), dict) else {}
    models_cfg = provider_cfg.get("models") if isinstance(provider_cfg.get("models"), dict) else {}

    matched_model = ""
    rates: Optional[Dict[str, float]] = None

    if model_name in models_cfg and isinstance(models_cfg.get(model_name), dict):
        matched_model = model_name
        rates = _normalize_rates(models_cfg[model_name])
    else:
        model_lower = model_name.lower()
        for configured_model, configured_rates in models_cfg.items():
            cfg_name = str(configured_model or "").strip()
            if not cfg_name or not isinstance(configured_rates, dict):
                continue
            cfg_lower = cfg_name.lower()
            if cfg_lower in model_lower or model_lower in cfg_lower:
                matched_model = cfg_name
                rates = _normalize_rates(configured_rates)
                break

    if rates is None:
        rates = _normalize_rates(catalog.get("defaults"))
        matched_model = ""

    return {
        "provider": provider_name,
        "model": model_name,
        "matched_model": matched_model,
        "pricing_version": str(catalog.get("pricing_version") or DEFAULT_PRICING_VERSION),
        "rates": rates,
    }


@lru_cache(maxsize=8)
def load_pricing_catalog(pricing_path: Optional[str] = None) -> Dict[str, Any]:
    env_path = os.getenv("SEED_LLM_PRICING_PATH")
    target = Path(pricing_path or env_path or _default_catalog_path())
    base = dict(DEFAULT_PRICING_CATALOG)

    if not target.exists():
        return base

    raw = target.read_text(encoding="utf-8")
    parsed: Any
    if target.suffix.lower() in {".yaml", ".yml"}:
        parsed = yaml.safe_load(raw) or {}
    else:
        parsed = json.loads(raw)

    if not isinstance(parsed, dict):
        return base

    merged = dict(base)
    for key, value in parsed.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            deep = dict(merged[key])
            deep.update(value)
            merged[key] = deep
        else:
            merged[key] = value
    return merged


def resolve_pricing_metadata(
    *,
    provider: str,
    model: str,
    pricing_path: Optional[str] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pricing_catalog = catalog or load_pricing_catalog(pricing_path=pricing_path)
    return _resolve_model_rates_from_catalog(provider=provider, model=model, catalog=pricing_catalog)

