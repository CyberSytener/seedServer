from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover
    Draft202012Validator = None


MODULE_REQUIRED_KEYS = [
    "catalog_version",
    "module_id",
    "title",
    "description",
    "input_schema",
    "output_schema",
    "side_effects",
    "required_scopes",
    "stability",
    "examples",
    "tags",
    "run_modes_supported",
    "idempotent",
    "timeout_sec",
    "retry_policy",
    "cost_profile",
    "risk_level",
    "depends_on",
    "produces",
]


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object: {path}")
    return payload


def _validate_tree(catalog_root: Path) -> List[str]:
    errors: List[str] = []
    tree_path = catalog_root / "tree.json"
    schema_path = catalog_root / "tree_schema_v0.json"

    tree = _load_json(tree_path)
    schema = _load_json(schema_path)

    if Draft202012Validator is not None:
        validator = Draft202012Validator(schema)
        for err in sorted(validator.iter_errors(tree), key=lambda item: str(list(item.path))):
            location = ".".join(str(part) for part in err.path) if list(err.path) else "$"
            errors.append(f"tree schema error at {location}: {err.message}")
    else:
        for key in ("catalog_version", "title", "root", "sections", "nodes"):
            if key not in tree:
                errors.append(f"tree missing key: {key}")

    nodes = tree.get("nodes") if isinstance(tree.get("nodes"), list) else []
    seen_ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{index}] must be object")
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            errors.append(f"nodes[{index}] missing id")
        elif node_id in seen_ids:
            errors.append(f"duplicate node id: {node_id}")
        seen_ids.add(node_id)

        raw_path = str(node.get("path") or "").strip().replace("\\", "/")
        if not raw_path:
            errors.append(f"nodes[{index}] missing path")
            continue
        if raw_path.startswith("/") or ".." in raw_path.split("/"):
            errors.append(f"nodes[{index}] invalid path: {raw_path}")
            continue
        file_path = (catalog_root / raw_path).resolve()
        if catalog_root.resolve() not in file_path.parents and file_path != catalog_root.resolve():
            errors.append(f"nodes[{index}] path escapes catalog root: {raw_path}")
            continue
        if not file_path.exists():
            errors.append(f"nodes[{index}] path does not exist: {raw_path}")

    return errors


def _validate_module_manifest(path: Path) -> List[str]:
    errors: List[str] = []
    payload = _load_json(path)

    for key in MODULE_REQUIRED_KEYS:
        if key not in payload:
            errors.append(f"missing key: {key}")

    module_id = str(payload.get("module_id") or "").strip()
    if module_id != path.stem:
        errors.append(f"module_id must match filename stem ({path.stem})")

    if payload.get("catalog_version") != "v0":
        errors.append("catalog_version must be v0")

    if not isinstance(payload.get("input_schema"), dict):
        errors.append("input_schema must be object")
    if not isinstance(payload.get("output_schema"), dict):
        errors.append("output_schema must be object")

    for key in ("side_effects", "required_scopes", "examples", "tags", "run_modes_supported", "depends_on", "produces"):
        if not isinstance(payload.get(key), list):
            errors.append(f"{key} must be list")

    if not isinstance(payload.get("idempotent"), bool):
        errors.append("idempotent must be boolean")

    timeout = payload.get("timeout_sec")
    if not isinstance(timeout, int) or timeout <= 0:
        errors.append("timeout_sec must be positive integer")

    retry_policy = payload.get("retry_policy")
    if not isinstance(retry_policy, dict):
        errors.append("retry_policy must be object")
    else:
        if not isinstance(retry_policy.get("max_retries"), int):
            errors.append("retry_policy.max_retries must be integer")
        if not isinstance(retry_policy.get("strategy"), str) or not retry_policy.get("strategy"):
            errors.append("retry_policy.strategy must be non-empty string")

    cost_profile = payload.get("cost_profile")
    if not isinstance(cost_profile, dict):
        errors.append("cost_profile must be object")
    else:
        if cost_profile.get("tier") not in {"low", "medium", "high"}:
            errors.append("cost_profile.tier must be low|medium|high")

    if payload.get("risk_level") not in {"low", "medium", "high", "critical"}:
        errors.append("risk_level must be low|medium|high|critical")

    stability = payload.get("stability")
    if stability not in {"stable", "experimental", "deprecated"}:
        errors.append("stability must be stable|experimental|deprecated")

    return errors


def _validate_modules(catalog_root: Path) -> List[str]:
    errors: List[str] = []
    modules_dir = catalog_root / "modules"
    files = sorted(modules_dir.glob("*.json"))
    if not files:
        return ["no module manifests found"]

    for file in files:
        manifest_errors = _validate_module_manifest(file)
        if manifest_errors:
            errors.append(f"[FAIL] {file.as_posix()}")
            errors.extend(f"  - {item}" for item in manifest_errors)
        else:
            print(f"[OK]   {file.as_posix()}")
    return errors


def main() -> int:
    catalog_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("app/catalog")
    if not catalog_root.exists():
        print(f"[FAIL] catalog root not found: {catalog_root}")
        return 1

    errors: List[str] = []
    errors.extend(_validate_tree(catalog_root))
    errors.extend(_validate_modules(catalog_root))

    if errors:
        print("[FAIL] catalog validation")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("[OK] catalog validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
