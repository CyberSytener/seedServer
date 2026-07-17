from __future__ import annotations

import ast
import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_PATHS = (
    ROOT / "app" / "contracts" / "opportunity",
    ROOT / "app" / "domain" / "opportunity",
    ROOT / "app" / "services" / "opportunity",
)
IMPORTABLE_PACKAGES = (
    "app.contracts.opportunity",
    "app.domain.opportunity",
    "app.services.opportunity",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "redis",
    "app.api",
    "app.infrastructure",
    "app.main",
    "app.settings",
    "app.core.llm",
    "app.services.llm_engine",
)


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_candidate_packages_exist_and_import_without_runtime_registration() -> None:
    for path in PACKAGE_PATHS:
        assert path.is_dir(), f"missing Candidate package: {path.relative_to(ROOT)}"
        assert (path / "__init__.py").is_file()

    for package_name in IMPORTABLE_PACKAGES:
        module = importlib.import_module(package_name)
        assert tuple(getattr(module, "__all__", ())) == ()


def test_candidate_packages_do_not_import_runtime_or_infrastructure() -> None:
    violations: list[str] = []
    for package_path in PACKAGE_PATHS:
        for python_file in sorted(package_path.rglob("*.py")):
            for imported_module in _imported_modules(python_file):
                if imported_module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    relative_path = python_file.relative_to(ROOT)
                    violations.append(f"{relative_path}: {imported_module}")

    assert violations == [], "forbidden Candidate imports:\n" + "\n".join(violations)
