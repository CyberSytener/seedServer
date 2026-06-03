from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_MODEL_TIERS = "cheap,balanced"
DEFAULT_TIMEOUT_SEC = 75
DEFAULT_MAX_GENERATE_RETRIES = 3


def _load_dotenv_if_present(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _mask(value: str, keep_start: int = 4, keep_end: int = 4) -> str:
    text = str(value or "")
    if len(text) <= keep_start + keep_end + 3:
        return "***"
    return f"{text[:keep_start]}***{text[-keep_end:]}"


def _redact_text(text: str) -> str:
    redacted = str(text or "")
    redacted = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "AIza***REDACTED***", redacted)
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._\-|:]+", "Bearer ***REDACTED***", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"(GEMINI_API_KEY\s*=\s*)([^\s]+)", r"\1***REDACTED***", redacted, flags=re.IGNORECASE)
    return redacted


def _redact_obj(payload: Any) -> Any:
    if isinstance(payload, dict):
        output: Dict[str, Any] = {}
        for key, value in payload.items():
            key_norm = str(key).lower()
            if any(token in key_norm for token in ("token", "secret", "api_key", "authorization")):
                output[key] = "***REDACTED***"
                continue
            output[key] = _redact_obj(value)
        return output
    if isinstance(payload, list):
        return [_redact_obj(item) for item in payload]
    if isinstance(payload, str):
        return _redact_text(payload)
    return payload


def _http_json(
    *,
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[Dict[str, Any]],
    timeout_sec: int,
) -> Tuple[int, Dict[str, Any]]:
    data: Optional[bytes] = None
    req_headers = dict(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=True).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=data, method=method, headers=req_headers)
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            status = int(resp.status)
            raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw.strip() else {}
            if not isinstance(payload, dict):
                payload = {"raw": payload}
            return status, payload
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {}
            if not isinstance(payload, dict):
                payload = {"raw": payload}
        except Exception:
            payload = {"raw": raw}
        return int(exc.code), payload


@dataclass
class SmokeStepResult:
    name: str
    status_code: int
    ok: bool
    summary: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SmokeRunSummary:
    base_url: str
    token_fingerprint: str
    selected_tier: Optional[str] = None
    selected_model: Optional[str] = None
    steps: List[SmokeStepResult] = field(default_factory=list)
    improve_steps: List[SmokeStepResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @property
    def elapsed_sec(self) -> float:
        return round(time.time() - self.started_at, 3)

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.steps)


def _build_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _build_sample_input() -> Dict[str, Any]:
    return {
        "ingredients": ["Eggs", "Spinach", "Tomato", "Olive Oil", "Onion"],
        "constraints": {
            "diet": "vegetarian",
            "allergens": ["peanut"],
            "calories_target": 550,
            "cuisine": "mediterranean",
            "time_limit": 30,
            "servings": 2,
        },
    }


def _extract_blueprint_shape(blueprint: Dict[str, Any]) -> Dict[str, Any]:
    steps = blueprint.get("steps") if isinstance(blueprint.get("steps"), list) else []
    return {
        "name": str(blueprint.get("name") or ""),
        "version": str(blueprint.get("version") or ""),
        "step_count": len(steps),
        "step_ids": [str(step.get("id") or step.get("name") or "") for step in steps if isinstance(step, dict)],
    }


def _canonical_block_name(raw_block: Any) -> str:
    block = str(raw_block or "").strip()
    lowered = block.lower()
    if lowered in {"neoeats.input.normalize", "normalize_input", "normalize_inventory", "normalize_pantry"}:
        return "neoeats.input.normalize"
    if lowered in {"neoeats.recipe.generate", "generate_recipe", "recipe_generate"}:
        return "neoeats.recipe.generate"
    if lowered in {"neoeats.recipe.validate", "validate_recipe", "recipe_validate"}:
        return "neoeats.recipe.validate"
    return block


def _repair_neoeats_blueprint_minimal(blueprint: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    if not isinstance(blueprint, dict):
        return {}, False
    repaired = json.loads(json.dumps(blueprint))
    changed = False

    if str(repaired.get("version") or "") != "v1":
        repaired["version"] = "v1"
        changed = True

    steps = repaired.get("steps")
    if not isinstance(steps, list):
        return repaired, changed

    normalize_id = ""
    generate_id = ""
    validate_id = ""
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or f"step_{idx}")
        block = _canonical_block_name(step.get("block") or step.get("block_type"))
        if str(step.get("id") or "") != step_id:
            step["id"] = step_id
            changed = True
        if str(step.get("block") or "") != block:
            step["block"] = block
            changed = True
        if not isinstance(step.get("inputs"), dict):
            step["inputs"] = {}
            changed = True
        lowered_id = step_id.lower()
        if block == "neoeats.input.normalize" or "normalize" in lowered_id:
            normalize_id = step_id
            step["block"] = "neoeats.input.normalize"
        elif block == "neoeats.recipe.generate" or "generate" in lowered_id:
            generate_id = step_id
            step["block"] = "neoeats.recipe.generate"
        elif block == "neoeats.recipe.validate" or "validate" in lowered_id:
            validate_id = step_id
            step["block"] = "neoeats.recipe.validate"

    if normalize_id and generate_id and validate_id:
        id_to_step = {
            str(step.get("id")): step
            for step in steps
            if isinstance(step, dict) and str(step.get("id") or "").strip()
        }

        normalize_step = id_to_step.get(normalize_id) or {}
        normalize_inputs = normalize_step.get("inputs") if isinstance(normalize_step.get("inputs"), dict) else {}
        if "ingredients" not in normalize_inputs:
            pantry_mapping = normalize_inputs.get("pantry")
            if isinstance(pantry_mapping, dict) and pantry_mapping.get("from"):
                normalize_inputs["ingredients"] = pantry_mapping
            else:
                normalize_inputs["ingredients"] = {"from": "payload.ingredients", "default": []}
            changed = True
        if "user_id" not in normalize_inputs:
            normalize_inputs["user_id"] = {"from": "user_id"}
            changed = True
        if "constraints" not in normalize_inputs:
            normalize_inputs["constraints"] = {"from": "payload.constraints", "default": {}}
            changed = True
        normalize_step["inputs"] = normalize_inputs
        id_to_step[normalize_id] = normalize_step

        generate_step = id_to_step.get(generate_id) or {}
        generate_inputs = generate_step.get("inputs") if isinstance(generate_step.get("inputs"), dict) else {}
        if "normalized" not in generate_inputs:
            generate_inputs["normalized"] = {"from": f"{normalize_id}.normalized"}
            changed = True
        generate_step["inputs"] = generate_inputs
        id_to_step[generate_id] = generate_step

        validate_step = id_to_step.get(validate_id) or {}
        validate_inputs = validate_step.get("inputs") if isinstance(validate_step.get("inputs"), dict) else {}
        if "recipe" not in validate_inputs:
            validate_inputs["recipe"] = {"from": f"{generate_id}.recipe"}
            changed = True
        if "constraints" not in validate_inputs:
            validate_inputs["constraints"] = {"from": f"{normalize_id}.normalized.constraints", "default": {}}
            changed = True
        validate_step["inputs"] = validate_inputs
        id_to_step[validate_id] = validate_step

        repaired["steps"] = [
            id_to_step.get(str(step.get("id")), step) if isinstance(step, dict) else step
            for step in steps
        ]

    return repaired, changed


def _short_details(payload: Dict[str, Any], max_len: int = 280) -> str:
    compact = json.dumps(_redact_obj(payload), ensure_ascii=False, default=str)
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len]}..."


def _is_real_model(model_name: Optional[str]) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    return not normalized.startswith("mock")


def _call_context_pack(
    *,
    base_url: str,
    headers: Dict[str, str],
    timeout_sec: int,
) -> SmokeStepResult:
    payload = {
        "domain": "neoeats",
        "intent": "recipe_from_inventory",
        "constraints": {
            "diet": "vegetarian",
            "time_limit": 30,
            "latency_budget_ms": 8000,
        },
        "max_modules": 50,
    }
    status, data = _http_json(
        method="POST",
        url=f"{base_url}/v1/catalog/context-pack",
        headers=headers,
        body=payload,
        timeout_sec=timeout_sec,
    )
    modules = data.get("module_candidates") if isinstance(data.get("module_candidates"), list) else []
    summary = {
        "module_candidates_count": len(modules),
        "matched_patterns_count": len(data.get("matched_patterns") or []),
    }
    return SmokeStepResult(
        name="context-pack",
        status_code=status,
        ok=status == 200,
        summary=summary,
        raw=data,
    )


def _call_generate_with_retry(
    *,
    base_url: str,
    headers: Dict[str, str],
    timeout_sec: int,
    model_tiers: List[str],
    max_retries: int,
    enable_client_repair: bool,
) -> Tuple[SmokeStepResult, Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    last_result: Optional[SmokeStepResult] = None
    last_blueprint: Optional[Dict[str, Any]] = None
    selected_tier: Optional[str] = None
    selected_model: Optional[str] = None

    prompt = (
        "Return ONLY a valid Seed blueprint JSON object.\n"
        "Required root keys: name, version, steps.\n"
        "Set version exactly to \"v1\".\n"
        "Use ONLY these block ids:\n"
        "1) neoeats.input.normalize\n"
        "2) neoeats.recipe.generate\n"
        "3) neoeats.recipe.validate\n"
        "Do NOT invent block names.\n"
        "Use mapping roots payload/request/user_id and prior step ids.\n"
        "Goal: recipe_from_inventory flow safe for STUB/DRY_RUN and SANDBOXED publish.\n"
    )
    for tier in model_tiers:
        for attempt in range(1, max_retries + 1):
            body = {
                "prompt": prompt,
                "domain": "neoeats",
                "constraints": {
                    "must_use_pattern": "inventory_check_then_recipe",
                    "safe_mode": True,
                },
                "model_tier": tier,
            }
            status, data = _http_json(
                method="POST",
                url=f"{base_url}/v1/blueprints/generate",
                headers=headers,
                body=body,
                timeout_sec=timeout_sec,
            )
            model = data.get("model") if isinstance(data.get("model"), dict) else {}
            blueprint = data.get("blueprint") if isinstance(data.get("blueprint"), dict) else {}
            normalized_blueprint = (
                data.get("normalized_blueprint") if isinstance(data.get("normalized_blueprint"), dict) else {}
            )
            if enable_client_repair:
                candidate_blueprint = normalized_blueprint or blueprint
                repaired_blueprint, repaired_applied = _repair_neoeats_blueprint_minimal(candidate_blueprint)
            else:
                repaired_blueprint = normalized_blueprint or blueprint
                repaired_applied = False
            model_name = str(model.get("model_name") or "")
            validation_ok = False
            validation_errors: List[str] = []
            if status == 200 and repaired_blueprint:
                v_status, v_data = _http_json(
                    method="POST",
                    url=f"{base_url}/v1/blueprints/validate",
                    headers=headers,
                    body={"blueprint": repaired_blueprint},
                    timeout_sec=timeout_sec,
                )
                validation_ok = v_status == 200 and bool(v_data.get("ok"))
                validation_errors = [str(item) for item in (v_data.get("errors") or [])]
            shape = _extract_blueprint_shape(repaired_blueprint)
            summary = {
                "attempt": attempt,
                "tier": tier,
                "model_name": model_name,
                "blueprint": shape,
                "repaired_blueprint": repaired_applied,
                "server_normalized": bool(normalized_blueprint),
                "validation_ok": validation_ok,
                "validation_errors_count": len(validation_errors),
                "validation_error_samples": validation_errors[:3],
            }
            step = SmokeStepResult(
                name="generate",
                status_code=status,
                ok=status == 200 and bool(blueprint),
                summary=summary,
                raw=data,
            )
            last_result = step
            last_blueprint = repaired_blueprint if repaired_blueprint else None

            if status == 200 and _is_real_model(model_name) and validation_ok:
                selected_tier = tier
                selected_model = model_name
                return step, last_blueprint, selected_tier, selected_model

            sleep_sec = min(4.0, (2 ** (attempt - 1)) + random.random())
            time.sleep(sleep_sec)

    return (
        last_result
        or SmokeStepResult(name="generate", status_code=0, ok=False, summary={"error": "no_attempts"}, raw={}),
        last_blueprint,
        selected_tier,
        selected_model,
    )


def _call_validate(
    *,
    base_url: str,
    headers: Dict[str, str],
    timeout_sec: int,
    blueprint: Dict[str, Any],
) -> SmokeStepResult:
    status, data = _http_json(
        method="POST",
        url=f"{base_url}/v1/blueprints/validate",
        headers=headers,
        body={"blueprint": blueprint},
        timeout_sec=timeout_sec,
    )
    summary = {
        "ok": bool(data.get("ok")),
        "errors_count": len(data.get("errors") or []),
        "warnings_count": len(data.get("warnings") or []),
    }
    return SmokeStepResult(
        name="validate",
        status_code=status,
        ok=status == 200 and bool(data.get("ok")),
        summary=summary,
        raw=data,
    )


def _call_dry_run(
    *,
    base_url: str,
    headers: Dict[str, str],
    timeout_sec: int,
    blueprint: Dict[str, Any],
) -> SmokeStepResult:
    status, data = _http_json(
        method="POST",
        url=f"{base_url}/v1/blueprints/dry-run",
        headers=headers,
        body={
            "blueprint": blueprint,
            "sample_input": _build_sample_input(),
            "mode": "STUB",
            "limits": {"max_steps": 25, "timeout_sec": 35},
        },
        timeout_sec=timeout_sec,
    )
    trace = data.get("execution_trace") if isinstance(data.get("execution_trace"), list) else []
    output_keys: List[str] = []
    if trace and isinstance(trace[-1], dict):
        output_keys = [str(item) for item in (trace[-1].get("output_keys") or []) if str(item)]
    summary = {
        "status": str(data.get("status") or ""),
        "runtime_execution_mode": str(data.get("runtime_execution_mode") or ""),
        "trace_length": len(trace),
        "last_output_keys": output_keys,
    }
    return SmokeStepResult(
        name="dry-run",
        status_code=status,
        ok=status == 200 and str(data.get("status") or "").lower() in {"succeeded", "success"},
        summary=summary,
        raw=data,
    )


def _call_publish(
    *,
    base_url: str,
    headers: Dict[str, str],
    timeout_sec: int,
    blueprint: Dict[str, Any],
) -> SmokeStepResult:
    generated_name = str(blueprint.get("name") or "neoeats_real_llm_smoke")
    unique_name = f"{generated_name}_sandboxed_{int(time.time())}"
    status, data = _http_json(
        method="POST",
        url=f"{base_url}/v1/blueprints/publish",
        headers=headers,
        body={
            "name": unique_name,
            "version": "v1",
            "blueprint": blueprint,
            "policy": {"target_status": "SANDBOXED", "require_admin_approval": True},
        },
        timeout_sec=timeout_sec,
    )
    summary = {
        "name": str(data.get("name") or unique_name),
        "status": str(data.get("status") or ""),
        "approval_required": bool(data.get("approval_required")),
    }
    return SmokeStepResult(
        name="publish",
        status_code=status,
        ok=status == 200 and str(data.get("status") or "").upper() == "SANDBOXED",
        summary=summary,
        raw=data,
    )


def _call_improve_once(
    *,
    base_url: str,
    headers: Dict[str, str],
    timeout_sec: int,
    blueprint: Dict[str, Any],
    model_tier: str,
    enable_client_repair: bool,
) -> List[SmokeStepResult]:
    shape = _extract_blueprint_shape(blueprint)
    improve_prompt = (
        "Improve this NeoEats blueprint once: make mappings explicit, keep STUB/DRY_RUN safe, "
        "and keep steps minimal. Return JSON only. Current blueprint summary: "
        + json.dumps(shape, ensure_ascii=True)
    )
    status_gen, data_gen = _http_json(
        method="POST",
        url=f"{base_url}/v1/blueprints/generate",
        headers=headers,
        body={"prompt": improve_prompt, "domain": "neoeats", "model_tier": model_tier},
        timeout_sec=timeout_sec,
    )
    model = data_gen.get("model") if isinstance(data_gen.get("model"), dict) else {}
    blueprint2 = data_gen.get("blueprint") if isinstance(data_gen.get("blueprint"), dict) else {}
    normalized_blueprint2 = (
        data_gen.get("normalized_blueprint") if isinstance(data_gen.get("normalized_blueprint"), dict) else {}
    )
    if enable_client_repair:
        repaired_blueprint2, repaired = _repair_neoeats_blueprint_minimal(normalized_blueprint2 or blueprint2)
    else:
        repaired_blueprint2 = normalized_blueprint2 or blueprint2
        repaired = False
    step_generate = SmokeStepResult(
        name="improve-generate",
        status_code=status_gen,
        ok=status_gen == 200 and bool(repaired_blueprint2),
        summary={
            "model_name": str(model.get("model_name") or ""),
            "blueprint": _extract_blueprint_shape(repaired_blueprint2),
            "repaired_blueprint": repaired,
            "validation_ok": bool((data_gen.get("validation") or {}).get("ok")),
        },
        raw=data_gen,
    )
    if not step_generate.ok:
        return [step_generate]

    step_validate = _call_validate(
        base_url=base_url,
        headers=headers,
        timeout_sec=timeout_sec,
        blueprint=repaired_blueprint2,
    )
    step_validate.name = "improve-validate"
    return [step_generate, step_validate]


def _print_result(summary: SmokeRunSummary) -> None:
    print("=== NeoEats Real LLM Smoke ===")
    print(f"base_url: {summary.base_url}")
    print(f"token: {summary.token_fingerprint}")
    print(f"selected_tier: {summary.selected_tier or 'n/a'}")
    print(f"selected_model: {_redact_text(summary.selected_model or 'n/a')}")
    print("")
    for step in summary.steps:
        state = "OK" if step.ok else "FAIL"
        print(f"[{state}] {step.name} status={step.status_code} summary={_short_details(step.summary)}")
    if summary.improve_steps:
        print("")
        print("improve_once:")
        for step in summary.improve_steps:
            state = "OK" if step.ok else "FAIL"
            print(f"[{state}] {step.name} status={step.status_code} summary={_short_details(step.summary)}")
    print("")
    print(f"overall_ok: {summary.ok}")
    print(f"elapsed_sec: {summary.elapsed_sec}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NeoEats real LLM smoke flow against /v1 agent surface.")
    parser.add_argument("--base-url", default=os.getenv("NEOEATS_SMOKE_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--timeout-sec", type=int, default=int(os.getenv("NEOEATS_SMOKE_TIMEOUT_SEC") or DEFAULT_TIMEOUT_SEC))
    parser.add_argument(
        "--token",
        default=os.getenv("NEOEATS_SMOKE_TOKEN"),
        help="Bearer token (optional). If omitted, a test token is generated for SEED_TEST_AUTH_MODE=1.",
    )
    parser.add_argument(
        "--model-tiers",
        default=os.getenv("NEOEATS_SMOKE_MODEL_TIERS") or DEFAULT_MODEL_TIERS,
        help="Comma-separated tiers to try for generation, e.g. cheap,balanced",
    )
    parser.add_argument(
        "--max-generate-retries",
        type=int,
        default=int(os.getenv("NEOEATS_SMOKE_MAX_GENERATE_RETRIES") or DEFAULT_MAX_GENERATE_RETRIES),
    )
    parser.add_argument(
        "--enable-client-repair",
        action="store_true",
        help="Enable legacy client-side blueprint repair fallback (disabled by default).",
    )
    parser.add_argument(
        "--no-repair",
        action="store_true",
        help="Force server-side normalization only (default behavior).",
    )
    parser.add_argument("--no-improve-pass", action="store_true", help="Disable optional improve-once pass.")
    return parser.parse_args()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    _load_dotenv_if_present(repo_root / ".env")

    args = parse_args()
    base_url = str(args.base_url).rstrip("/")
    token = args.token or "test_neoeats-smoke|developer|catalog:read,blueprints:write,runs:write"
    headers = _build_headers(token)
    token_fingerprint = _mask(token, keep_start=6, keep_end=6)

    model_tiers = [part.strip() for part in str(args.model_tiers).split(",") if part.strip()]
    if not model_tiers:
        model_tiers = ["cheap", "balanced"]

    summary = SmokeRunSummary(
        base_url=base_url,
        token_fingerprint=token_fingerprint,
    )
    enable_client_repair = bool(args.enable_client_repair) and not bool(args.no_repair)

    context_pack = _call_context_pack(base_url=base_url, headers=headers, timeout_sec=args.timeout_sec)
    summary.steps.append(context_pack)
    if not context_pack.ok:
        _print_result(summary)
        return 1

    generate_step, blueprint, selected_tier, selected_model = _call_generate_with_retry(
        base_url=base_url,
        headers=headers,
        timeout_sec=args.timeout_sec,
        model_tiers=model_tiers,
        max_retries=max(1, min(int(args.max_generate_retries), 5)),
        enable_client_repair=enable_client_repair,
    )
    summary.steps.append(generate_step)
    summary.selected_tier = selected_tier
    summary.selected_model = selected_model or str((generate_step.raw.get("model") or {}).get("model_name") or "")
    if not generate_step.ok or not blueprint:
        _print_result(summary)
        return 1
    if not _is_real_model(summary.selected_model):
        print("generation did not use a real provider model (received mock/fallback model).", file=sys.stderr)
        _print_result(summary)
        return 2

    validate_step = _call_validate(
        base_url=base_url,
        headers=headers,
        timeout_sec=args.timeout_sec,
        blueprint=blueprint,
    )
    summary.steps.append(validate_step)
    if not validate_step.ok:
        _print_result(summary)
        return 1

    dry_run_step = _call_dry_run(
        base_url=base_url,
        headers=headers,
        timeout_sec=args.timeout_sec,
        blueprint=blueprint,
    )
    summary.steps.append(dry_run_step)
    if not dry_run_step.ok:
        _print_result(summary)
        return 1

    publish_step = _call_publish(
        base_url=base_url,
        headers=headers,
        timeout_sec=args.timeout_sec,
        blueprint=blueprint,
    )
    summary.steps.append(publish_step)
    if not publish_step.ok:
        _print_result(summary)
        return 1

    if not args.no_improve_pass:
        improve_tier = summary.selected_tier or "cheap"
        summary.improve_steps = _call_improve_once(
            base_url=base_url,
            headers=headers,
            timeout_sec=args.timeout_sec,
            blueprint=blueprint,
            model_tier=improve_tier,
            enable_client_repair=enable_client_repair,
        )

    _print_result(summary)
    return 0 if summary.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
