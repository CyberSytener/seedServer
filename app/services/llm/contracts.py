from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.llm.pricing import DEFAULT_PRICING_VERSION, resolve_pricing_metadata


DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
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
    "gpt-4.1-mini": {
        "input_per_1k_tokens_usd": 0.00015,
        "output_per_1k_tokens_usd": 0.00060,
        "credit_multiplier": 1.2,
    },
}


@dataclass(frozen=True)
class UsageBreakdown:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    request_count: int = 1
    cached_tokens: Optional[int] = None
    tool_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": int(self.prompt_tokens),
            "completion_tokens": int(self.completion_tokens),
            "total_tokens": int(self.total_tokens),
            "request_count": int(self.request_count),
            "cached_tokens": self.cached_tokens,
            "tool_tokens": self.tool_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass(frozen=True)
class CreditLedgerEvent:
    provider: str
    model: str
    endpoint: str
    feature: str
    stage: str
    usage: UsageBreakdown
    estimated_cost_usd: float
    credits_charged: int
    attempt: int = 1
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    job_id: Optional[str] = None
    pricing_version: str = DEFAULT_PRICING_VERSION
    matched_pricing_model: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "endpoint": self.endpoint,
            "feature": self.feature,
            "stage": self.stage,
            "usage": self.usage.to_dict(),
            "estimated_cost_usd": float(self.estimated_cost_usd),
            "credits_charged": int(self.credits_charged),
            "attempt": int(self.attempt),
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "job_id": self.job_id,
            "pricing_version": self.pricing_version,
            "matched_pricing_model": self.matched_pricing_model,
            "created_at": self.created_at,
        }


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else default
    except Exception:
        return default


def normalize_usage_breakdown(raw_usage: Dict[str, Any] | None, *, request_count: int = 1) -> UsageBreakdown:
    usage = raw_usage or {}

    prompt_tokens = _coerce_int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
    completion_tokens = _coerce_int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
    total_tokens = _coerce_int(usage.get("total_tokens", prompt_tokens + completion_tokens))

    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    if completion_tokens <= 0 and total_tokens > prompt_tokens:
        completion_tokens = total_tokens - prompt_tokens

    return UsageBreakdown(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        request_count=max(1, _coerce_int(request_count, 1)),
        cached_tokens=_coerce_int(usage.get("cached_tokens"), 0) if usage.get("cached_tokens") is not None else None,
        tool_tokens=_coerce_int(usage.get("tool_tokens"), 0) if usage.get("tool_tokens") is not None else None,
        reasoning_tokens=_coerce_int(usage.get("reasoning_tokens"), 0) if usage.get("reasoning_tokens") is not None else None,
    )


def _resolve_model_rates_legacy(model: str, pricing_table: dict[str, dict[str, float]]) -> dict[str, float]:
    if model in pricing_table:
        return pricing_table[model]

    model_lower = model.lower()
    for configured_model, rates in pricing_table.items():
        if configured_model.lower() in model_lower or model_lower in configured_model.lower():
            return rates

    return {
        "input_per_1k_tokens_usd": 0.0,
        "output_per_1k_tokens_usd": 0.0,
        "credit_multiplier": 1.0,
    }


def _resolve_rates(
    *,
    provider: str,
    model: str,
    pricing_table: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    if pricing_table:
        rates = _resolve_model_rates_legacy(model, pricing_table)
        return {
            "rates": rates,
            "pricing_version": "custom",
            "matched_pricing_model": model if model in pricing_table else None,
        }

    pricing_meta = resolve_pricing_metadata(provider=provider, model=model)
    rates = pricing_meta.get("rates") if isinstance(pricing_meta.get("rates"), dict) else {}
    return {
        "rates": rates,
        "pricing_version": str(pricing_meta.get("pricing_version") or DEFAULT_PRICING_VERSION),
        "matched_pricing_model": str(pricing_meta.get("matched_model") or "").strip() or None,
    }


def build_credit_ledger_event(
    *,
    provider: str,
    model: str,
    endpoint: str,
    feature: str,
    stage: str,
    usage: UsageBreakdown,
    attempt: int = 1,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
    pricing_table: dict[str, dict[str, float]] | None = None,
) -> CreditLedgerEvent:
    provider_name = str(provider or "unknown").strip().lower() or "unknown"
    model_name = str(model or "unknown").strip() or "unknown"
    resolved = _resolve_rates(
        provider=provider_name,
        model=model_name,
        pricing_table=pricing_table,
    )
    rates = resolved.get("rates") if isinstance(resolved.get("rates"), dict) else {}

    prompt_cost = (usage.prompt_tokens / 1000.0) * float(rates.get("input_per_1k_tokens_usd", 0.0))
    completion_cost = (usage.completion_tokens / 1000.0) * float(rates.get("output_per_1k_tokens_usd", 0.0))
    estimated_cost_usd = prompt_cost + completion_cost

    credits_multiplier = max(0.1, float(rates.get("credit_multiplier", 1.0)))
    credits_charged = int(round(usage.total_tokens * credits_multiplier))

    return CreditLedgerEvent(
        provider=provider_name,
        model=model_name,
        endpoint=endpoint,
        feature=feature,
        stage=stage,
        usage=usage,
        estimated_cost_usd=estimated_cost_usd,
        credits_charged=credits_charged,
        attempt=max(1, int(attempt)),
        trace_id=trace_id,
        session_id=session_id,
        job_id=job_id,
        pricing_version=str(resolved.get("pricing_version") or DEFAULT_PRICING_VERSION),
        matched_pricing_model=resolved.get("matched_pricing_model"),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def summarize_ledger_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    total_cost_usd = 0.0
    total_credits_charged = 0
    totals_by_session: dict[str, dict[str, Any]] = {}
    totals_by_job: dict[str, dict[str, Any]] = {}

    for event in events:
        event_cost = float(event.get("estimated_cost_usd") or 0.0)
        event_credits = int(event.get("credits_charged") or 0)
        total_cost_usd += event_cost
        total_credits_charged += event_credits

        session_id = event.get("session_id")
        if session_id:
            scoped = totals_by_session.setdefault(
                str(session_id),
                {"total_cost_usd": 0.0, "total_credits_charged": 0},
            )
            scoped["total_cost_usd"] += event_cost
            scoped["total_credits_charged"] += event_credits

        job_id = event.get("job_id")
        if job_id:
            scoped = totals_by_job.setdefault(
                str(job_id),
                {"total_cost_usd": 0.0, "total_credits_charged": 0},
            )
            scoped["total_cost_usd"] += event_cost
            scoped["total_credits_charged"] += event_credits

    return {
        "total_cost_usd": total_cost_usd,
        "total_credits_charged": total_credits_charged,
        "cost_breakdown": events,
        "totals_by_session": totals_by_session,
        "totals_by_job": totals_by_job,
    }
