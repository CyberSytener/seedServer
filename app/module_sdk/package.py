from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from app.contracts import validate_module_contract
from app.module_sdk.runtime import ModuleDiagnostic, ModuleExecutionContext, ModuleResult, execute_module


@dataclass(frozen=True)
class ModulePackage:
    root: Path
    manifest_path: Path
    handler_path: Optional[Path]

    def load_manifest(self) -> Dict[str, Any]:
        data = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("module manifest must be a mapping")
        return data


def _diagnostic(code: str, path: str, message: str) -> ModuleDiagnostic:
    return ModuleDiagnostic(code=code, path=path, message=message)


def resolve_module_package(target: str | Path, *, registry_root: Path = Path("modules")) -> ModulePackage:
    requested = Path(target)
    candidates = [requested]
    if not requested.exists():
        candidates.extend([registry_root / requested, registry_root / f"{requested}.yaml"])

    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() in {".yaml", ".yml"}:
            handler_path = candidate.parent / "handler.py"
            return ModulePackage(
                root=candidate.parent,
                manifest_path=candidate,
                handler_path=handler_path if handler_path.exists() else None,
            )
        if candidate.is_dir():
            manifests = [
                path
                for path in (candidate / "module.yaml", candidate / "module.yml")
                if path.exists()
            ]
            if not manifests:
                manifests = sorted([*candidate.glob("*.yaml"), *candidate.glob("*.yml")])
            if len(manifests) == 1:
                handler_path = candidate / "handler.py"
                return ModulePackage(
                    root=candidate,
                    manifest_path=manifests[0],
                    handler_path=handler_path if handler_path.exists() else None,
                )
            if len(manifests) > 1:
                raise ValueError(f"multiple manifests found under {candidate}")
    raise FileNotFoundError(f"module target not found: {target}")


def validate_handler_dependencies(path: Path, allowed: Iterable[str]) -> List[ModuleDiagnostic]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [_diagnostic("sdk.handler_syntax", str(path), str(exc))]

    allowed_roots = {item.split(".")[0] for item in allowed if item}
    diagnostics: List[ModuleDiagnostic] = []
    for node in ast.walk(tree):
        imported: List[str] = []
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                diagnostics.append(
                    _diagnostic(
                        "sdk.relative_import_not_allowed",
                        f"{path}:{getattr(node, 'lineno', 1)}",
                        "relative imports are not supported by the SDK package loader",
                    )
                )
                continue
            if node.module:
                imported = [node.module]
        for name in imported:
            root = name.split(".")[0]
            if name == "app.module_sdk":
                continue
            if name.startswith("app.module_sdk."):
                diagnostics.append(
                    _diagnostic(
                        "sdk.internal_sdk_import",
                        f"{path}:{getattr(node, 'lineno', 1)}",
                        f"import '{name}' bypasses the stable app.module_sdk public interface",
                    )
                )
                continue
            if root == "app":
                diagnostics.append(
                    _diagnostic(
                        "sdk.platform_internal_import",
                        f"{path}:{getattr(node, 'lineno', 1)}",
                        f"import '{name}' bypasses the stable app.module_sdk interface",
                    )
                )
                continue
            if root in sys.stdlib_module_names or root in allowed_roots:
                continue
            diagnostics.append(
                _diagnostic(
                    "sdk.dependency_not_allowed",
                    f"{path}:{getattr(node, 'lineno', 1)}",
                    f"import '{name}' is not in dependencies.python",
                )
            )
    return diagnostics


def validate_module_package(package: ModulePackage) -> Dict[str, Any]:
    diagnostics: List[ModuleDiagnostic] = []
    try:
        manifest = package.load_manifest()
    except Exception as exc:  # noqa: BLE001
        diagnostics.append(_diagnostic("sdk.manifest_unreadable", str(package.manifest_path), str(exc)))
        manifest = {}

    diagnostics.extend(
        _diagnostic(issue.code, issue.path, issue.message)
        for issue in validate_module_contract(manifest)
    )
    pipeline = str(manifest.get("pipeline") or "")
    if pipeline == "sdk_module":
        if package.handler_path is None:
            diagnostics.append(
                _diagnostic("sdk.handler_missing", str(package.root / "handler.py"), "sdk_module requires handler.py")
            )
        else:
            dependencies = manifest.get("dependencies") if isinstance(manifest.get("dependencies"), dict) else {}
            python_dependencies = dependencies.get("python") if isinstance(dependencies.get("python"), list) else []
            diagnostics.extend(validate_handler_dependencies(package.handler_path, python_dependencies))

    return {
        "ok": not diagnostics,
        "module_id": str(manifest.get("mode_id") or ""),
        "manifest": str(package.manifest_path),
        "handler": str(package.handler_path) if package.handler_path else None,
        "diagnostics": [item.model_dump() for item in diagnostics],
    }


def _load_handler(path: Path) -> Any:
    module_name = f"seed_sdk_module_{path.parent.name}_{path.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise ImportError(f"unable to load handler from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler_class = getattr(module, "Handler", None)
    if not inspect.isclass(handler_class):
        raise ValueError("handler.py must export a Handler class")
    return handler_class()


def run_module_package_tests(package: ModulePackage) -> Dict[str, Any]:
    validation = validate_module_package(package)
    if not validation["ok"]:
        return {**validation, "cases": [], "passed": 0, "failed": 0}

    manifest = package.load_manifest()
    if str(manifest.get("pipeline") or "") != "sdk_module":
        diagnostic = _diagnostic(
            "sdk.test_unsupported_pipeline",
            "$.pipeline",
            "local SDK tests currently require pipeline 'sdk_module'",
        )
        return {
            **validation,
            "ok": False,
            "diagnostics": [diagnostic.model_dump()],
            "cases": [],
            "passed": 0,
            "failed": 0,
        }

    try:
        handler = _load_handler(package.handler_path or package.root / "handler.py")
    except Exception as exc:  # noqa: BLE001
        diagnostic = _diagnostic("sdk.handler_load_failed", str(package.handler_path), str(exc))
        return {
            **validation,
            "ok": False,
            "diagnostics": [diagnostic.model_dump()],
            "cases": [],
            "passed": 0,
            "failed": 0,
        }

    tests = manifest.get("tests") if isinstance(manifest.get("tests"), dict) else {}
    golden = tests.get("golden") if isinstance(tests.get("golden"), list) else []
    cases: List[Dict[str, Any]] = []
    for index, case in enumerate(golden):
        inputs = case.get("input") if isinstance(case, dict) and isinstance(case.get("input"), dict) else {}
        expected = case.get("expect_fields") if isinstance(case, dict) and isinstance(case.get("expect_fields"), list) else []
        context = ModuleExecutionContext(
            module_id=str(manifest.get("mode_id") or "unknown"),
            run_id=f"sdk-test-{index + 1}",
            execution_mode="test",
            capabilities=[str(item) for item in manifest.get("capabilities") or []],
        )
        result: ModuleResult = asyncio.run(
            execute_module(
                handler,
                context=context,
                inputs=inputs,
                input_schema=manifest.get("input_schema") if isinstance(manifest.get("input_schema"), dict) else {},
                output_schema=manifest.get("output_schema") if isinstance(manifest.get("output_schema"), dict) else {},
            )
        )
        missing = [field for field in expected if field not in result.output]
        passed = result.status == "succeeded" and not missing
        cases.append(
            {
                "index": index,
                "ok": passed,
                "status": result.status,
                "missing_fields": missing,
                "result": result.model_dump(),
            }
        )

    passed_count = sum(1 for case in cases if case["ok"])
    return {
        **validation,
        "ok": passed_count == len(cases) and len(cases) > 0,
        "cases": cases,
        "passed": passed_count,
        "failed": len(cases) - passed_count,
    }


def create_module_package(
    module_id: str,
    *,
    registry_root: Path = Path("modules"),
    title: Optional[str] = None,
    description: Optional[str] = None,
    force: bool = False,
) -> ModulePackage:
    normalized = module_id.strip().lower()
    if not normalized or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_" for ch in normalized):
        raise ValueError("module_id must contain only lowercase letters, numbers, and underscores")
    if not normalized[0].isalpha() or len(normalized) < 2:
        raise ValueError("module_id must start with a letter and contain at least two characters")

    root = registry_root / normalized
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"module package already exists: {root}")
    root.mkdir(parents=True, exist_ok=True)

    manifest_path = root / "module.yaml"
    handler_path = root / "handler.py"
    readme_path = root / "README.md"
    files = {
        manifest_path: _manifest_template(normalized, title=title, description=description),
        handler_path: _handler_template(),
        readme_path: _readme_template(normalized),
    }
    for path, content in files.items():
        if path.exists() and not force:
            raise FileExistsError(f"refusing to overwrite {path}")
        path.write_text(content, encoding="utf-8")
    return ModulePackage(root=root, manifest_path=manifest_path, handler_path=handler_path)


def _manifest_template(module_id: str, *, title: Optional[str], description: Optional[str]) -> str:
    display_title = title or module_id.replace("_", " ").title()
    display_description = description or f"SDK module {display_title}."
    manifest = {
        "contract_version": "1.0.0",
        "mode_id": module_id,
        "pipeline": "sdk_module",
        "module_version": "0.1.0",
        "title": display_title,
        "description": display_description,
        "owner": {"team": "unassigned"},
        "lifecycle": "draft",
        "breaking_changes": False,
        "migrations": [],
        "prompt_versions": [f"{module_id}.handler.v1"],
        "rubric_versions": [f"{module_id}.rubric.v1"],
        "task_type": module_id,
        "capabilities": [],
        "dependencies": {"python": []},
        "errors": [
            {
                "code": "invalid_request",
                "retryable": False,
                "description": "The module input does not satisfy its declared schema.",
            }
        ],
        "execution": {
            "adapter": "module_sdk",
            "timeout_seconds": 30,
            "max_retries": 0,
            "idempotent": True,
            "deterministic": True,
        },
        "effects": {
            "side_effects": False,
            "compensation_supported": False,
            "network_access": "none",
            "filesystem_access": "none",
        },
        "security": {"trust_level": "untrusted", "secret_refs": []},
        "resources": {
            "memory_mb": 128,
            "max_concurrency": 1,
            "max_cost_units": 1.0,
            "providers": ["module_sdk"],
        },
        "compatibility": {"accepts_contract_versions": ["1.x"], "module_dependencies": []},
        "evidence": {
            "documentation": [f"modules/{module_id}/README.md"],
            "examples": [f"seed module test {module_id}"],
        },
        "input_schema": {
            "type": "object",
            "required": ["request"],
            "properties": {"request": {"type": "string", "minLength": 1}},
        },
        "output_schema": {
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "string"}},
        },
        "tests": {
            "golden": [
                {
                    "input": {"request": "hello"},
                    "expect_fields": ["result"],
                }
            ],
            "cost_regression": {"max_avg_cost_units": 1.0},
        },
    }
    return yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False)


def _handler_template() -> str:
    return '''from __future__ import annotations

from typing import Any, Dict

from app.module_sdk import ModuleExecutionContext


class Handler:
    async def execute(
        self,
        context: ModuleExecutionContext,
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        del context
        return {"result": str(inputs["request"])}
'''


def _readme_template(module_id: str) -> str:
    return f"""# {module_id}

Generated Seed SDK module package.

```bash
seed module validate {module_id}
seed module test {module_id}
seed module sandbox {module_id}
seed module sandbox {module_id} --runtime docker
seed module qualify {module_id}
seed module status {module_id}
seed module publish {module_id} --actor reviewer --reason "approved release"
seed module history {module_id}
```

Edit `module.yaml` to declare the contract and `handler.py` to implement it.
"""
