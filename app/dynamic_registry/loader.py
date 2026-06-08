from __future__ import annotations

import importlib.util
import inspect
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def registry_dir() -> Path:
    return Path(__file__).resolve().parent


def ensure_registry_dir() -> Path:
    path = registry_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_block_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in (name or ""))
    safe = safe.strip("_") or "dynamic_block"
    return safe


def write_block_file(block_name: str, code: str) -> Path:
    base = sanitize_block_name(block_name)
    path = ensure_registry_dir() / f"{base}.py"
    path.write_text(code, encoding="utf-8")

    meta_path = ensure_registry_dir() / f"{base}.json"
    meta_payload = {
        "block_name": block_name,
        "safe_name": base,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write dynamic block metadata: %s", exc)

    return path


def load_block_from_path(path: Path, base_cls: type) -> type:
    module_name = f"dynamic_registry.{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise ImportError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    block_classes: list[type] = []
    for obj in module.__dict__.values():
        if inspect.isclass(obj) and issubclass(obj, base_cls) and obj is not base_cls:
            block_classes.append(obj)

    if not block_classes:
        raise ValueError(f"No block class found in {path.name}")
    if len(block_classes) > 1:
        raise ValueError(f"Multiple block classes found in {path.name}")

    return block_classes[0]


def iter_block_files() -> Iterable[Path]:
    path = ensure_registry_dir()
    for entry in sorted(path.glob("*.py")):
        if entry.name in {"__init__.py", "loader.py"}:
            continue
        yield entry


def register_dynamic_blocks(registry: Any, base_cls: type) -> None:
    for entry in iter_block_files():
        try:
            block_cls = load_block_from_path(entry, base_cls)
            block_name = getattr(block_cls, "NAME", None) or block_cls.__name__
            registry.register(block_name, block_cls)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load dynamic block %s: %s", entry.name, exc)
