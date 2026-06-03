from __future__ import annotations

from pathlib import Path

from app.core.realtime.sagas.llm_policy import (
    build_policy_snapshot,
    load_llm_orchestration_policy,
    resolve_llm_policy,
)


def test_resolve_llm_policy_exposes_versioned_registry_surface():
    load_llm_orchestration_policy.cache_clear()
    policy = resolve_llm_policy(payload={}, task_type="general")

    assert policy["policy_version"] == "v1"
    assert str(policy.get("pricing_version") or "").strip()
    assert isinstance(policy.get("prompt_registry"), dict)
    assert isinstance(policy.get("rubric_registry"), dict)
    assert str((policy.get("prompt_registry") or {}).get("plan", {}).get("version") or "").strip()
    assert str((policy.get("rubric_registry") or {}).get("json", {}).get("version") or "").strip()

    snapshot = policy.get("policy_snapshot") or {}
    assert snapshot.get("policy_version") == policy["policy_version"]
    assert snapshot.get("pricing_version") == policy["pricing_version"]
    assert str(snapshot.get("fingerprint") or "").strip()


def test_resolve_llm_policy_accepts_nested_registry_shape(tmp_path: Path):
    policy_path = tmp_path / "llm_policy.yaml"
    policy_path.write_text(
        """
version: v_legacy
pricing_version: legacy-pricing
registry:
  policy_version: orch.v2
  pricing_version: 2026-02-19
  prompt_registry:
    plan: { version: plan.v9, sha256: "abc123" }
  rubric_registry:
    json: { version: rubric.json.v3, sha256: "def456" }
task_policies:
  default:
    default_mode: fast
    steps:
      plan: { tier: cheap, prompt_ref: plan }
      validate: { tier: cheap, rubric_ref: json }
""".strip(),
        encoding="utf-8",
    )
    load_llm_orchestration_policy.cache_clear()
    policy = resolve_llm_policy(payload={}, task_type="general", policy_path=str(policy_path))

    assert policy["policy_version"] == "orch.v2"
    assert policy["pricing_version"] == "2026-02-19"
    assert policy["prompt_registry"]["plan"]["version"] == "plan.v9"
    assert policy["rubric_registry"]["json"]["version"] == "rubric.json.v3"

    step_snapshot = build_policy_snapshot(
        policy,
        mode="fast",
        task_type="general",
        step_name="validate",
        step_policy={"rubric_ref": "json"},
    )
    assert step_snapshot["step_rubric_ref"] == "json"
    assert step_snapshot["step_rubric_version"] == "rubric.json.v3"
    assert str(step_snapshot.get("fingerprint") or "").strip()
