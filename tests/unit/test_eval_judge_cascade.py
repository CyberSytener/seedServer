from __future__ import annotations

from app.services.evals import build_judge_trace, resolve_judge_cascade_policy


def _policy_with_judge(*, threshold: float = 0.9, trust_or_escalate: bool = True):
    return {
        "steps": {
            "validate": {
                "ensemble": [
                    {
                        "kind": "llm_judge",
                        "tier": "balanced",
                        "trust_or_escalate": trust_or_escalate,
                        "confidence_threshold": threshold,
                        "escalate_tier": "powerful",
                        "cheap_cost_units": 0.01,
                        "escalate_cost_units": 0.07,
                    }
                ]
            }
        }
    }


def test_resolve_judge_policy_disabled_without_llm_judge():
    policy = resolve_judge_cascade_policy({"steps": {"validate": {"ensemble": []}}})

    assert policy.enabled is False
    assert policy.trust_or_escalate is False
    assert policy.cheap_tier == "cheap"


def test_build_judge_trace_escalates_when_confidence_below_threshold():
    policy = resolve_judge_cascade_policy(_policy_with_judge(threshold=0.99, trust_or_escalate=True))
    trace = build_judge_trace(
        schema_gate={"is_pass": True, "violations": []},
        quality_gate={"is_pass": True, "score": 85, "violations": []},
        candidate_reports=[
            {"quality_gate": {"score": 85}},
            {"quality_gate": {"score": 55}},
        ],
        pass_score=85,
        policy=policy,
    )

    assert trace["enabled"] is True
    assert trace["escalated"] is True
    assert trace["decision_source"] == "escalated_judge"
    assert trace["estimated_total_cost_units"] > trace["cheap_judge"]["estimated_cost_units"]
    assert trace["escalated_judge"]["estimated_cost_units"] == 0.07


def test_build_judge_trace_skips_escalation_when_confident():
    policy = resolve_judge_cascade_policy(_policy_with_judge(threshold=0.75, trust_or_escalate=True))
    trace = build_judge_trace(
        schema_gate={"is_pass": True, "violations": []},
        quality_gate={"is_pass": True, "score": 96, "violations": []},
        candidate_reports=[{"quality_gate": {"score": 96}}],
        pass_score=85,
        policy=policy,
    )

    assert trace["enabled"] is True
    assert trace["escalated"] is False
    assert trace["decision_source"] == "cheap_judge"
    assert trace["estimated_total_cost_units"] == trace["cheap_judge"]["estimated_cost_units"]


def test_build_judge_trace_single_judge_mode_without_escalation():
    policy = resolve_judge_cascade_policy(_policy_with_judge(threshold=0.99, trust_or_escalate=False))
    trace = build_judge_trace(
        schema_gate={"is_pass": True, "violations": []},
        quality_gate={"is_pass": True, "score": 85, "violations": []},
        candidate_reports=[
            {"quality_gate": {"score": 85}},
            {"quality_gate": {"score": 30}},
        ],
        pass_score=85,
        policy=policy,
    )

    assert trace["enabled"] is True
    assert trace["strategy"] == "single_judge"
    assert trace["escalated"] is False
    assert "escalated_judge" not in trace
