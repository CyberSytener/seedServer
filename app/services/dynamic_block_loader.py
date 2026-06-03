from __future__ import annotations

import ast
import inspect
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from app.core.blocks import BlockBase, BlockRegistry
from app.dynamic_registry import loader as registry_loader


_ALLOWED_IMPORTS = {
    "typing",
    "dataclasses",
    "datetime",
    "uuid",
    "math",
    "json",
}

_FORBIDDEN_NAMES = {
    "__import__",
    "open",
    "exec",
    "eval",
    "compile",
    "globals",
    "locals",
    "input",
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
}

_CAPABILITY_BY_IMPORT_ROOT = {
    "socket": "network",
    "httpx": "network",
    "requests": "network",
    "urllib": "network",
    "os": "filesystem",
    "pathlib": "filesystem",
    "subprocess": "process",
}

_CAPABILITY_BY_FORBIDDEN_NAME = {
    "socket": "network",
    "open": "filesystem",
    "os": "filesystem",
    "pathlib": "filesystem",
    "subprocess": "process",
    "exec": "process",
    "eval": "process",
    "compile": "process",
    "globals": "runtime_introspection",
    "locals": "runtime_introspection",
    "input": "runtime_interaction",
}


@dataclass
class BlockDraftResult:
    ok: bool
    block_name: str | None = None
    code: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: dict[str, Any] | None = None
    status: str = "DRAFT"


class DynamicBlockLoader:
    def __init__(self, registry: BlockRegistry) -> None:
        self._registry = registry

    def validate_code(self, code: str) -> list[str]:
        errors: list[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return [f"syntax_error: {exc}"]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] not in _ALLOWED_IMPORTS:
                        errors.append(f"forbidden_import: {alias.name}")
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[0] not in _ALLOWED_IMPORTS:
                    errors.append(f"forbidden_import: {mod}")
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
                errors.append(f"forbidden_name: {node.id}")
        return errors

    def scan_capabilities(self, code: str) -> dict[str, Any]:
        """
        Derive coarse capability requirements and explicit violations from code.

        This complements validate_code() and is used by publish gate checks.
        """
        required_capabilities: set[str] = set()
        violations: list[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return {
                "required_capabilities": ["compute"],
                "violations": [f"syntax_error: {exc}"],
                "passed": False,
            }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    capability = _CAPABILITY_BY_IMPORT_ROOT.get(root)
                    if capability:
                        required_capabilities.add(capability)
                    if root not in _ALLOWED_IMPORTS:
                        violations.append(f"forbidden_import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                capability = _CAPABILITY_BY_IMPORT_ROOT.get(root)
                if capability:
                    required_capabilities.add(capability)
                if root not in _ALLOWED_IMPORTS:
                    violations.append(f"forbidden_import: {node.module or ''}")
            elif isinstance(node, ast.Name):
                capability = _CAPABILITY_BY_FORBIDDEN_NAME.get(node.id)
                if capability:
                    required_capabilities.add(capability)
                if node.id in _FORBIDDEN_NAMES:
                    violations.append(f"forbidden_name: {node.id}")

        if not required_capabilities:
            required_capabilities.add("compute")

        normalized_violations = sorted(set(violations))
        return {
            "required_capabilities": sorted(required_capabilities),
            "violations": normalized_violations,
            "passed": len(normalized_violations) == 0,
        }

    def load_block(self, code: str) -> type[BlockBase]:
        safe_builtins = {
            "range": range,
            "len": len,
            "min": min,
            "max": max,
            "sum": sum,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "dict": dict,
            "list": list,
            "set": set,
            "tuple": tuple,
            "enumerate": enumerate,
            "zip": zip,
            "any": any,
            "all": all,
        }

        def _safe_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
            root = name.split(".")[0]
            if root not in _ALLOWED_IMPORTS:
                raise ImportError(f"Import not allowed: {name}")
            return __import__(name, globals, locals, fromlist, level)

        safe_builtins["__import__"] = _safe_import

        globals_dict = {"__builtins__": safe_builtins, "BlockBase": BlockBase}
        locals_dict: dict[str, Any] = {}
        exec(code, globals_dict, locals_dict)

        block_classes = []
        for obj in locals_dict.values():
            if inspect.isclass(obj) and issubclass(obj, BlockBase):
                if obj is not BlockBase:
                    block_classes.append(obj)

        if not block_classes:
            raise ValueError("No BlockBase subclass found in generated code")
        if len(block_classes) > 1:
            raise ValueError("Multiple BlockBase subclasses found; expected exactly one")

        block_cls = block_classes[0]
        if not isinstance(getattr(block_cls, "INPUT_SCHEMA", None), dict):
            raise ValueError("Block missing INPUT_SCHEMA dict")
        if not isinstance(getattr(block_cls, "OUTPUT_SCHEMA", None), dict):
            raise ValueError("Block missing OUTPUT_SCHEMA dict")

        return block_cls

    def save_block(self, block_name: str, code: str) -> str:
        path = registry_loader.write_block_file(block_name, code)
        return str(path)

    def load_block_from_path(self, path: str) -> type[BlockBase]:
        block_cls = registry_loader.load_block_from_path(Path(path), BlockBase)
        return block_cls

    async def dry_run(self, block_cls: type[BlockBase]) -> dict[str, Any]:
        sample_inputs = self._sample_inputs(block_cls)
        block = block_cls(engine=None, params={})
        result = await block.execute({}, sample_inputs)
        return {
            "status": "succeeded",
            "output": result,
        }

    def register(self, name: str, block_cls: type[BlockBase]) -> None:
        self._registry.register(name, block_cls)

    @staticmethod
    def _sample_inputs(block_cls: type[BlockBase]) -> dict[str, Any]:
        schema = getattr(block_cls, "INPUT_SCHEMA", {}) or {}
        properties = schema.get("properties") if isinstance(schema, dict) else {}
        required = schema.get("required") if isinstance(schema, dict) else []
        inputs: dict[str, Any] = {}
        for key in required or []:
            spec = properties.get(key, {}) if isinstance(properties, dict) else {}
            inputs[key] = _sample_value(spec)
        return inputs


def _sample_value(spec: dict[str, Any]) -> Any:
    kind = spec.get("type") if isinstance(spec, dict) else None
    if kind == "string":
        return "test"
    if kind == "number":
        return 0.0
    if kind == "integer":
        return 0
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        return {}
    return None
