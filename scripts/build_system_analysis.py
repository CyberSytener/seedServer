from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.0.0"
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
    "system-analysis-artifacts",
}
DEFAULT_EXCLUDED_GLOBS = (
    "**/.env",
    "**/.env.*",
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/*.log",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.zip",
)
ROUTE_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace", "websocket"}
COMPOSITION_CALLS = {
    "add_api_route",
    "add_event_handler",
    "add_middleware",
    "include_router",
    "mount",
    "register",
}
ENV_CALL_NAMES = {"getenv"}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def _path_matches(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    normalized_pattern = pattern.replace("\\", "/")
    if normalized_pattern.endswith("/**"):
        prefix = normalized_pattern[:-3].rstrip("/")
        return normalized == prefix or normalized.startswith(prefix + "/")
    return fnmatch.fnmatch(normalized, normalized_pattern)


def _is_excluded(relative_path: Path, excluded_dirs: set[str], excluded_globs: tuple[str, ...]) -> bool:
    if any(part in excluded_dirs for part in relative_path.parts):
        return True
    value = relative_path.as_posix()
    return any(_path_matches(value, pattern) for pattern in excluded_globs)


def iter_repository_files(root: Path, profile: dict[str, Any]) -> Iterable[Path]:
    excluded_dirs = DEFAULT_EXCLUDED_DIRS | set(profile.get("exclude_dirs", []))
    excluded_globs = DEFAULT_EXCLUDED_GLOBS + tuple(profile.get("exclude_globs", []))
    for path in sorted(root.rglob("*"), key=lambda candidate: candidate.as_posix()):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if _is_excluded(relative_path, excluded_dirs, excluded_globs):
            continue
        yield path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _qualified_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _qualified_name(node.func)
    if isinstance(node, ast.Subscript):
        return _qualified_name(node.value)
    return ""


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _module_name(relative_path: Path) -> str:
    parts = list(relative_path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _surface_name(module_name: str) -> str:
    parts = module_name.split(".")
    if len(parts) >= 2 and parts[0] in {"app", "tests"}:
        return ".".join(parts[:2])
    return parts[0] if parts else module_name


def _collect_imports(tree: ast.AST) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return sorted(set(imports))


def _collect_routes(tree: ast.AST, relative_path: str) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                method = ""
                owner = ""
                if isinstance(decorator.func, ast.Attribute):
                    method = decorator.func.attr.lower()
                    owner = _qualified_name(decorator.func.value)
                if method not in ROUTE_METHODS:
                    continue
                path = _literal_string(decorator.args[0]) if decorator.args else None
                routes.append(
                    {
                        "file": relative_path,
                        "function": node.name,
                        "line": node.lineno,
                        "method": method.upper(),
                        "owner": owner,
                        "path": path,
                    }
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "add_api_route":
                continue
            path = _literal_string(node.args[0]) if node.args else None
            routes.append(
                {
                    "file": relative_path,
                    "function": None,
                    "line": node.lineno,
                    "method": "ADD_API_ROUTE",
                    "owner": _qualified_name(node.func.value),
                    "path": path,
                }
            )
    return routes


def _collect_environment_references(tree: ast.AST, relative_path: str) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _qualified_name(node.func)
            is_getenv = name in ENV_CALL_NAMES or name.endswith(".getenv") or name.endswith("environ.get")
            if is_getenv and node.args:
                key = _literal_string(node.args[0])
                if key:
                    references.append({"file": relative_path, "line": node.lineno, "name": key})
        elif isinstance(node, ast.Subscript) and _qualified_name(node.value).endswith("environ"):
            key = _literal_string(node.slice)
            if key:
                references.append({"file": relative_path, "line": node.lineno, "name": key})
    return references


def _collect_python_facts(path: Path, root: Path) -> dict[str, Any]:
    relative_path = path.relative_to(root).as_posix()
    text = read_text(path)
    facts: dict[str, Any] = {
        "file": relative_path,
        "module": _module_name(path.relative_to(root)),
        "lines": line_count(text),
        "imports": [],
        "classes": [],
        "functions": [],
        "routes": [],
        "composition_calls": [],
        "environment_references": [],
        "broad_exception_handlers": 0,
        "pass_statements": 0,
        "todo_markers": len(re.findall(r"(?i)\b(?:TODO|FIXME|HACK)\b", text)),
        "parse_error": None,
    }
    try:
        tree = ast.parse(text, filename=relative_path)
    except SyntaxError as exc:
        facts["parse_error"] = {"line": exc.lineno, "message": exc.msg}
        return facts

    facts["imports"] = _collect_imports(tree)
    facts["routes"] = _collect_routes(tree, relative_path)
    facts["environment_references"] = _collect_environment_references(tree, relative_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = sorted(filter(None, (_qualified_name(base) for base in node.bases)))
            facts["classes"].append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "bases": bases,
                    "is_pydantic_model": any(base.endswith("BaseModel") for base in bases),
                    "is_protocol": any(base.endswith("Protocol") for base in bases),
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            facts["functions"].append(
                {
                    "name": node.name,
                    "line": node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                }
            )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in COMPOSITION_CALLS:
                facts["composition_calls"].append(
                    {
                        "call": node.func.attr,
                        "owner": _qualified_name(node.func.value),
                        "line": node.lineno,
                    }
                )
        elif isinstance(node, ast.ExceptHandler):
            handler_name = _qualified_name(node.type)
            if node.type is None or handler_name in {"Exception", "BaseException"}:
                facts["broad_exception_handlers"] += 1
        elif isinstance(node, ast.Pass):
            facts["pass_statements"] += 1

    facts["classes"] = sorted(facts["classes"], key=lambda item: (item["line"], item["name"]))
    facts["functions"] = sorted(facts["functions"], key=lambda item: (item["line"], item["name"]))
    facts["composition_calls"] = sorted(
        facts["composition_calls"], key=lambda item: (item["line"], item["call"], item["owner"])
    )
    facts["environment_references"] = sorted(
        facts["environment_references"], key=lambda item: (item["name"], item["file"], item["line"])
    )
    return facts


def _load_pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {"exists": False, "project": {}, "dependencies": [], "optional_dependencies": {}}
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    return {
        "exists": True,
        "project": {
            "name": project.get("name"),
            "version": project.get("version"),
            "requires_python": project.get("requires-python"),
        },
        "dependencies": sorted(project.get("dependencies", [])),
        "optional_dependencies": {
            key: sorted(value) for key, value in sorted(project.get("optional-dependencies", {}).items())
        },
    }


def _load_quality_gates(root: Path) -> dict[str, Any]:
    path = root / "scripts" / "run_quality_gate.py"
    if not path.is_file():
        return {"exists": False, "choices": [], "test_inventories": {}}
    try:
        tree = ast.parse(read_text(path), filename=path.as_posix())
    except SyntaxError as exc:
        return {"exists": True, "choices": [], "test_inventories": {}, "parse_error": exc.msg}

    constants: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        try:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue

    inventories = {
        name: list(value)
        for name, value in sorted(constants.items())
        if name.endswith("_TESTS") and isinstance(value, (list, tuple))
    }
    choices = constants.get("GATE_CHOICES", ())
    return {
        "exists": True,
        "choices": list(choices) if isinstance(choices, (list, tuple)) else [],
        "test_inventories": inventories,
    }


def _load_workflows(root: Path) -> list[dict[str, Any]]:
    workflows: list[dict[str, Any]] = []
    workflow_root = root / ".github" / "workflows"
    if not workflow_root.is_dir():
        return workflows
    for path in sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))):
        text = read_text(path)
        match = re.search(r"(?m)^name:\s*(.+?)\s*$", text)
        workflows.append(
            {
                "file": path.relative_to(root).as_posix(),
                "name": match.group(1).strip('"\'') if match else path.stem,
                "lines": line_count(text),
            }
        )
    return workflows


def _evaluate_surfaces(files: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for surface in profile.get("surfaces", []):
        patterns = surface.get("paths", [])
        matched = [item for item in files if any(_path_matches(item["path"], pattern) for pattern in patterns)]
        results.append(
            {
                "id": surface["id"],
                "status": surface["status"],
                "description": surface.get("description", ""),
                "paths": patterns,
                "file_count": len(matched),
                "python_file_count": sum(1 for item in matched if item["suffix"] == ".py"),
                "test_file_count": sum(1 for item in matched if item["path"].startswith("tests/")),
            }
        )
    return results


def _evaluate_boundaries(python_files: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for boundary in profile.get("boundaries", []):
        source_patterns = boundary.get("source_paths", [])
        forbidden_prefixes = tuple(boundary.get("forbidden_import_prefixes", []))
        for item in python_files:
            if not any(_path_matches(item["file"], pattern) for pattern in source_patterns):
                continue
            for imported in item["imports"]:
                if imported.startswith(forbidden_prefixes):
                    violations.append(
                        {
                            "boundary_id": boundary["id"],
                            "file": item["file"],
                            "import": imported,
                            "severity": boundary.get("severity", "warning"),
                        }
                    )
    return sorted(violations, key=lambda item: (item["boundary_id"], item["file"], item["import"]))


def build_inventory(root: Path, profile: dict[str, Any], revision: str = "working-tree") -> dict[str, Any]:
    root = root.resolve()
    repository_files: list[dict[str, Any]] = []
    python_files: list[dict[str, Any]] = []
    extension_counts: Counter[str] = Counter()
    top_level_counts: Counter[str] = Counter()

    for path in iter_repository_files(root, profile):
        relative_path = path.relative_to(root)
        text = read_text(path) if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", "Makefile"} else ""
        suffix = path.suffix.lower() or f"<{path.name}>"
        file_record = {
            "path": relative_path.as_posix(),
            "suffix": suffix,
            "bytes": path.stat().st_size,
            "lines": line_count(text),
        }
        repository_files.append(file_record)
        extension_counts[suffix] += 1
        top_level_counts[relative_path.parts[0]] += 1
        if path.suffix.lower() == ".py":
            python_files.append(_collect_python_facts(path, root))

    internal_edges: Counter[tuple[str, str]] = Counter()
    for item in python_files:
        source = _surface_name(item["module"])
        for imported in item["imports"]:
            if imported.startswith("app."):
                internal_edges[(source, _surface_name(imported))] += 1

    routes = sorted(
        [route for item in python_files for route in item["routes"]],
        key=lambda item: (item["file"], item["line"], item["method"], item.get("path") or ""),
    )
    environment_references = sorted(
        [reference for item in python_files for reference in item["environment_references"]],
        key=lambda item: (item["name"], item["file"], item["line"]),
    )
    composition_points = sorted(
        [
            {"file": item["file"], **call}
            for item in python_files
            for call in item["composition_calls"]
        ],
        key=lambda item: (item["file"], item["line"], item["call"]),
    )

    thresholds = profile.get("hotspot_thresholds", {})
    line_threshold = int(thresholds.get("line_count", 600))
    function_threshold = int(thresholds.get("function_count", 40))
    class_threshold = int(thresholds.get("class_count", 20))
    hotspots = sorted(
        [
            {
                "file": item["file"],
                "lines": item["lines"],
                "functions": len(item["functions"]),
                "classes": len(item["classes"]),
                "broad_exception_handlers": item["broad_exception_handlers"],
                "pass_statements": item["pass_statements"],
                "todo_markers": item["todo_markers"],
            }
            for item in python_files
            if item["lines"] >= line_threshold
            or len(item["functions"]) >= function_threshold
            or len(item["classes"]) >= class_threshold
        ],
        key=lambda item: (-item["lines"], item["file"]),
    )

    required_docs = []
    for value in profile.get("required_docs", []):
        path = root / value
        required_docs.append({"path": value, "exists": path.is_file()})

    pydantic_models = sorted(
        [
            {"file": item["file"], "name": cls["name"], "line": cls["line"]}
            for item in python_files
            for cls in item["classes"]
            if cls["is_pydantic_model"]
        ],
        key=lambda item: (item["file"], item["line"], item["name"]),
    )
    protocols = sorted(
        [
            {"file": item["file"], "name": cls["name"], "line": cls["line"]}
            for item in python_files
            for cls in item["classes"]
            if cls["is_protocol"]
        ],
        key=lambda item: (item["file"], item["line"], item["name"]),
    )

    inventory = {
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "profile": {
            "schema_version": profile.get("schema_version"),
            "repository": profile.get("repository"),
        },
        "summary": {
            "files": len(repository_files),
            "python_files": len(python_files),
            "python_lines": sum(item["lines"] for item in python_files),
            "test_files": sum(1 for item in repository_files if item["path"].startswith("tests/")),
            "documentation_files": sum(1 for item in repository_files if item["suffix"] == ".md"),
            "routes": len(routes),
            "pydantic_models": len(pydantic_models),
            "protocols": len(protocols),
            "workflows": len(_load_workflows(root)),
            "boundary_violations": 0,
            "python_parse_errors": sum(1 for item in python_files if item["parse_error"]),
        },
        "files": {
            "by_extension": dict(sorted(extension_counts.items())),
            "by_top_level": dict(sorted(top_level_counts.items())),
            "largest": sorted(repository_files, key=lambda item: (-item["lines"], item["path"]))[:30],
        },
        "surfaces": _evaluate_surfaces(repository_files, profile),
        "python": {
            "dependency_edges": [
                {"source": source, "target": target, "imports": count}
                for (source, target), count in sorted(internal_edges.items())
            ],
            "routes": routes,
            "composition_points": composition_points,
            "environment_references": environment_references,
            "pydantic_models": pydantic_models,
            "protocols": protocols,
            "hotspots": hotspots,
            "parse_errors": [
                {"file": item["file"], **item["parse_error"]}
                for item in python_files
                if item["parse_error"]
            ],
            "broad_exception_handlers": sum(item["broad_exception_handlers"] for item in python_files),
            "pass_statements": sum(item["pass_statements"] for item in python_files),
            "todo_markers": sum(item["todo_markers"] for item in python_files),
        },
        "boundaries": {
            "violations": _evaluate_boundaries(python_files, profile),
        },
        "quality": {
            "gates": _load_quality_gates(root),
            "workflows": _load_workflows(root),
        },
        "documentation": {
            "required": required_docs,
            "adrs": sorted(
                path.relative_to(root).as_posix()
                for path in (root / "docs" / "adr").glob("*.md")
                if path.is_file()
            )
            if (root / "docs" / "adr").is_dir()
            else [],
        },
        "dependencies": _load_pyproject(root),
    }
    inventory["summary"]["boundary_violations"] = len(inventory["boundaries"]["violations"])
    return inventory


def render_markdown(inventory: dict[str, Any]) -> str:
    summary = inventory["summary"]
    lines = [
        "# Seed System Analysis Inventory",
        "",
        f"Schema: `{inventory['schema_version']}`  ",
        f"Revision: `{inventory['revision']}`",
        "",
        "This file is generated from repository facts. It is evidence for analysis, not a product-status declaration.",
        "",
        "## Executive Inventory",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in (
        "files",
        "python_files",
        "python_lines",
        "test_files",
        "documentation_files",
        "routes",
        "pydantic_models",
        "protocols",
        "workflows",
        "boundary_violations",
        "python_parse_errors",
    ):
        lines.append(f"| `{key}` | {summary[key]} |")

    lines.extend(["", "## Declared Surfaces vs Repository Files", "", "| Surface | Status | Files | Python | Tests |", "| --- | --- | ---: | ---: | ---: |"]) 
    for surface in inventory["surfaces"]:
        lines.append(
            f"| `{surface['id']}` | {surface['status']} | {surface['file_count']} | "
            f"{surface['python_file_count']} | {surface['test_file_count']} |"
        )

    lines.extend(["", "## Python Hotspots", "", "| File | Lines | Functions | Classes | Broad catches | Pass | TODO |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]) 
    hotspots = inventory["python"]["hotspots"]
    if hotspots:
        for item in hotspots:
            lines.append(
                f"| `{item['file']}` | {item['lines']} | {item['functions']} | {item['classes']} | "
                f"{item['broad_exception_handlers']} | {item['pass_statements']} | {item['todo_markers']} |"
            )
    else:
        lines.append("| _none above configured thresholds_ | 0 | 0 | 0 | 0 | 0 | 0 |")

    lines.extend(["", "## Boundary Signals", ""])
    violations = inventory["boundaries"]["violations"]
    if violations:
        for item in violations:
            lines.append(
                f"- **{item['severity']}** `{item['boundary_id']}`: `{item['file']}` imports `{item['import']}`."
            )
    else:
        lines.append("- No configured boundary violation was detected.")

    lines.extend(["", "## Composition and API Signals", ""])
    lines.append(f"- Route decorators or registrations: **{len(inventory['python']['routes'])}**")
    lines.append(f"- Composition calls: **{len(inventory['python']['composition_points'])}**")
    lines.append(
        f"- Distinct environment variable names: **{len({item['name'] for item in inventory['python']['environment_references']})}**"
    )

    lines.extend(["", "## Quality Gates", ""])
    gate_data = inventory["quality"]["gates"]
    if gate_data.get("exists"):
        lines.append("- Gate choices: " + ", ".join(f"`{value}`" for value in gate_data.get("choices", [])))
        for name, paths in gate_data.get("test_inventories", {}).items():
            lines.append(f"- `{name}`: {len(paths)} configured paths")
    else:
        lines.append("- `scripts/run_quality_gate.py` was not found.")

    lines.extend(["", "## Interpretation Rules", ""])
    lines.extend(
        [
            "1. **Declared** claims come from maintained scope, roadmap, ADR, and strategy documents.",
            "2. **Observed** claims come from this generated inventory and direct source inspection.",
            "3. **Verified** claims require a focused test, workflow, or reproducible command result.",
            "4. **Inferred** claims must state their evidence and uncertainty; they are not treated as runtime truth.",
            "",
            "Use `docs/system-analysis/TASK_ROUTE_TEMPLATE.md` to convert these facts into a target-specific route.",
            "",
        ]
    )
    return "\n".join(lines)


def write_artifacts(inventory: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "inventory.json"
    markdown_path = output_dir / "inventory.md"
    json_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(inventory), encoding="utf-8")
    return json_path, markdown_path


def load_profile(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported analysis profile schema {data.get('schema_version')!r}; expected {SCHEMA_VERSION!r}"
        )
    if not data.get("repository"):
        raise ValueError("Analysis profile must declare repository")
    return data


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build a deterministic, non-secret Seed repository inventory.")
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--profile", type=Path, default=root / "docs" / "system-analysis" / "profile.json")
    parser.add_argument("--output-dir", type=Path, default=root / "system-analysis-artifacts")
    parser.add_argument("--revision", default=os.getenv("GITHUB_SHA", "working-tree"))
    parser.add_argument(
        "--fail-on-boundary-violation",
        action="store_true",
        help="Return a non-zero code when configured dependency boundaries are violated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        profile = load_profile(args.profile)
        inventory = build_inventory(args.root, profile, revision=args.revision)
        json_path, markdown_path = write_artifacts(inventory, args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"system-analysis error: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {json_path}")
    print(f"wrote {markdown_path}")
    print(json.dumps(inventory["summary"], indent=2, sort_keys=True))
    if args.fail_on_boundary_violation and inventory["summary"]["boundary_violations"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
