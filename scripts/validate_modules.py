from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml


REQUIRED_KEYS = [
    "mode_id",
    "pipeline",
    "input_schema",
    "output_schema",
    "tests",
    "module_version",
    "breaking_changes",
    "migrations",
    "prompt_versions",
    "rubric_versions",
]
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _iter_module_files(root: Path) -> List[Path]:
    return sorted(list(root.glob("**/*.yaml")) + list(root.glob("**/*.yml")))


def _load(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("module spec must be a mapping")
    return data


def _validate(path: Path, spec: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    for key in REQUIRED_KEYS:
        if key not in spec:
            errors.append(f"missing key: {key}")

    if str(spec.get("pipeline") or "") != "llm_pipeline":
        errors.append("only llm_pipeline is currently supported")

    input_schema = spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else None
    if not input_schema:
        errors.append("input_schema must be an object")

    output_schema = spec.get("output_schema") if isinstance(spec.get("output_schema"), dict) else None
    if not output_schema:
        errors.append("output_schema must be an object")

    module_version = spec.get("module_version")
    if not isinstance(module_version, str) or not module_version.strip():
        errors.append("module_version must be non-empty semver string")
    elif not SEMVER_RE.fullmatch(module_version.strip()):
        errors.append("module_version must be valid semver (e.g. 1.2.3)")

    if not isinstance(spec.get("breaking_changes"), bool):
        errors.append("breaking_changes must be boolean")

    migrations = spec.get("migrations")
    if not isinstance(migrations, list):
        errors.append("migrations must be a list")
    else:
        for index, migration in enumerate(migrations):
            if not isinstance(migration, dict):
                errors.append(f"migrations[{index}] must be object")

    prompt_versions = spec.get("prompt_versions")
    if not isinstance(prompt_versions, list) or not prompt_versions:
        errors.append("prompt_versions must be non-empty list")
    else:
        for index, version in enumerate(prompt_versions):
            if not isinstance(version, str) or not version.strip():
                errors.append(f"prompt_versions[{index}] must be non-empty string")

    rubric_versions = spec.get("rubric_versions")
    if not isinstance(rubric_versions, list) or not rubric_versions:
        errors.append("rubric_versions must be non-empty list")
    else:
        for index, version in enumerate(rubric_versions):
            if not isinstance(version, str) or not version.strip():
                errors.append(f"rubric_versions[{index}] must be non-empty string")

    tests = spec.get("tests") if isinstance(spec.get("tests"), dict) else None
    if not tests:
        errors.append("tests must be an object")
        return errors

    golden = tests.get("golden") if isinstance(tests.get("golden"), list) else []
    if not golden:
        errors.append("tests.golden must contain at least one case")
    else:
        for index, case in enumerate(golden):
            if not isinstance(case, dict):
                errors.append(f"tests.golden[{index}] must be object")
                continue
            if not isinstance(case.get("input"), dict):
                errors.append(f"tests.golden[{index}].input must be object")
            if not isinstance(case.get("expect_fields"), list) or not case.get("expect_fields"):
                errors.append(f"tests.golden[{index}].expect_fields must be non-empty list")

    cost_regression = tests.get("cost_regression") if isinstance(tests.get("cost_regression"), dict) else {}
    max_avg_cost_units = cost_regression.get("max_avg_cost_units")
    if max_avg_cost_units is None:
        errors.append("tests.cost_regression.max_avg_cost_units is required")
    else:
        try:
            if float(max_avg_cost_units) <= 0:
                errors.append("tests.cost_regression.max_avg_cost_units must be > 0")
        except Exception:
            errors.append("tests.cost_regression.max_avg_cost_units must be numeric")

    return errors


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("modules")
    files = _iter_module_files(root)
    if not files:
        print(f"No module files found under {root}")
        return 1

    has_errors = False
    for path in files:
        try:
            spec = _load(path)
            errors = _validate(path, spec)
        except Exception as exc:  # noqa: BLE001
            errors = [str(exc)]

        if errors:
            has_errors = True
            print(f"[FAIL] {path}")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"[OK]   {path}")

    return 1 if has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
