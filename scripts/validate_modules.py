from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts import validate_module_contract


def _iter_module_files(root: Path) -> List[Path]:
    return sorted(list(root.glob("**/*.yaml")) + list(root.glob("**/*.yml")))


def _load(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("module spec must be a mapping")
    return data


def _validate(path: Path, spec: Dict[str, Any]) -> List[str]:
    del path
    return [issue.as_message() for issue in validate_module_contract(spec)]


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
