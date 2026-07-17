from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = ROOT / "app"
VALIDATED_ADAPTER = (
    APP_ROOT
    / "core"
    / "realtime"
    / "sagas"
    / "flows"
    / "validated_flow_executor.py"
)
DIRECT_EXECUTOR_MODULE = "app.core.realtime.sagas.flows.flow_executor"


def _imports_direct_executor(path: Path) -> bool:
    source = path.read_text(encoding="utf-8-sig", errors="replace")
    if "FlowExecutorSaga" not in source or "flow_executor" not in source:
        return False

    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == DIRECT_EXECUTOR_MODULE for alias in node.names):
                return True
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        imports_executor_class = any(
            alias.name == "FlowExecutorSaga" for alias in node.names
        )
        if not imports_executor_class:
            continue
        if node.module == DIRECT_EXECUTOR_MODULE:
            return True
        if node.level and node.module == "flow_executor":
            return True
    return False


def test_production_code_does_not_bypass_validated_flow_executor_export() -> None:
    offenders: list[str] = []
    for python_file in sorted(APP_ROOT.rglob("*.py")):
        if python_file == VALIDATED_ADAPTER:
            continue
        if _imports_direct_executor(python_file):
            offenders.append(str(python_file.relative_to(ROOT)))

    assert offenders == [], (
        "production code must import FlowExecutorSaga from "
        "app.core.realtime.sagas.flows; direct historical executor imports: "
        + ", ".join(offenders)
    )
