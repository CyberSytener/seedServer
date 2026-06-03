from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class JudgeCascadePolicy:
    enabled: bool
    trust_or_escalate: bool
    confidence_threshold: float
    cheap_tier: str
    escalate_tier: str
    cheap_cost_units: float
    escalate_cost_units: float


def _normalized_threshold(value: Any, default: float = 0.85) -> float:
    try:
        threshold = float(value)
    except Exception:
        threshold = default
    if threshold < 0.0:
        return 0.0
    if threshold > 1.0:
        return 1.0
    return threshold


def _normalized_cost_units(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(0.0, parsed)


def resolve_judge_cascade_policy(policy: Dict[str, Any]) -> JudgeCascadePolicy:
    steps_cfg = policy.get("steps") if isinstance(policy.get("steps"), dict) else {}
    validate_cfg = steps_cfg.get("validate") if isinstance(steps_cfg.get("validate"), dict) else {}
    ensemble = validate_cfg.get("ensemble") if isinstance(validate_cfg.get("ensemble"), list) else []

    llm_judge_cfg: Dict[str, Any] = {}
    for entry in ensemble:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("kind") or "").strip().lower() != "llm_judge":
            continue
        llm_judge_cfg = entry
        break

    if not llm_judge_cfg:
        return JudgeCascadePolicy(
            enabled=False,
            trust_or_escalate=False,
            confidence_threshold=0.85,
            cheap_tier="cheap",
            escalate_tier="powerful",
            cheap_cost_units=0.01,
            escalate_cost_units=0.05,
        )

    return JudgeCascadePolicy(
        enabled=True,
        trust_or_escalate=bool(llm_judge_cfg.get("trust_or_escalate")),
        confidence_threshold=_normalized_threshold(llm_judge_cfg.get("confidence_threshold"), 0.85),
        cheap_tier=str(llm_judge_cfg.get("tier") or "cheap"),
        escalate_tier=str(llm_judge_cfg.get("escalate_tier") or "powerful"),
        cheap_cost_units=_normalized_cost_units(llm_judge_cfg.get("cheap_cost_units"), 0.01),
        escalate_cost_units=_normalized_cost_units(llm_judge_cfg.get("escalate_cost_units"), 0.05),
    )


def _candidate_scores(candidate_reports: List[Dict[str, Any]]) -> List[int]:
    scores: List[int] = []
    for item in candidate_reports:
        if not isinstance(item, dict):
            continue
        quality_gate = item.get("quality_gate") if isinstance(item.get("quality_gate"), dict) else {}
        scores.append(int(quality_gate.get("score") or 0))
    return scores


def _judge_confidence(
    *,
    schema_pass: bool,
    quality_pass: bool,
    score: int,
    candidate_scores: List[int],
    candidate_count: int,
) -> float:
    spread_penalty = 0.0
    if candidate_scores:
        spread_penalty = min(0.25, (max(candidate_scores) - min(candidate_scores)) / 100.0)
    consensus_penalty = min(0.2, max(0, candidate_count - 1) * 0.05)
    schema_penalty = 0.0 if schema_pass else 0.4
    quality_penalty = 0.0 if quality_pass else 0.3
    return max(
        0.0,
        min(
            1.0,
            (score / 100.0) - spread_penalty - consensus_penalty - schema_penalty - quality_penalty,
        ),
    )


def build_judge_trace(
    *,
    schema_gate: Dict[str, Any],
    quality_gate: Dict[str, Any],
    candidate_reports: List[Dict[str, Any]],
    pass_score: int,
    policy: JudgeCascadePolicy,
) -> Dict[str, Any]:
    score = int(quality_gate.get("score") or 0)
    schema_pass = bool(schema_gate.get("is_pass"))
    quality_pass = bool(quality_gate.get("is_pass"))
    scores = _candidate_scores(candidate_reports)
    confidence = _judge_confidence(
        schema_pass=schema_pass,
        quality_pass=quality_pass,
        score=score,
        candidate_scores=scores,
        candidate_count=len(candidate_reports),
    )

    cheap_pass = bool(schema_pass and quality_pass and score >= int(pass_score))
    trace: Dict[str, Any] = {
        "enabled": policy.enabled,
        "strategy": "trust_or_escalate" if policy.trust_or_escalate else "single_judge",
        "cheap_judge": {
            "tier": policy.cheap_tier,
            "score": score,
            "pass": cheap_pass,
            "confidence": round(confidence, 4),
            "estimated_cost_units": round(policy.cheap_cost_units, 6),
        },
        "confidence_threshold": float(policy.confidence_threshold),
        "escalated": False,
        "decision_source": "cheap_judge",
        "estimated_total_cost_units": round(policy.cheap_cost_units, 6),
    }

    if not policy.trust_or_escalate:
        return trace

    if confidence >= policy.confidence_threshold:
        return trace

    escalated_confidence = min(1.0, confidence + 0.05)
    escalated_pass = cheap_pass
    trace["escalated"] = True
    trace["decision_source"] = "escalated_judge"
    trace["estimated_total_cost_units"] = round(policy.cheap_cost_units + policy.escalate_cost_units, 6)
    trace["escalated_judge"] = {
        "tier": policy.escalate_tier,
        "score": score,
        "pass": escalated_pass,
        "confidence": round(escalated_confidence, 4),
        "reason": "confidence_below_threshold",
        "estimated_cost_units": round(policy.escalate_cost_units, 6),
    }
    return trace
