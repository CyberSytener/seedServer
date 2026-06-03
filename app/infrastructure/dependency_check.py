"""Runtime dependency checker

Reads `CREATED_DEPENDENCIES.md` and attempts to import listed packages.
Logs missing packages with actionable messages.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "CREATED_DEPENDENCIES.md"

# Some packages expose different import names than the pip package name.
COMMON_IMPORT_ALIASES = {
    "PyJWT": "jwt",
    "psycopg2-binary": "psycopg2",
}

logger = logging.getLogger(__name__)


def _parse_md_packages() -> List[str]:
    if not MD.exists():
        return []
    packages: List[str] = []
    lines = MD.read_text(encoding="utf-8").splitlines()
    for ln in lines:
        ln = ln.strip()
        # We expect table rows like: | 2026-02-01 | package==x | ... |
        if ln.startswith("|") and "|" in ln[1:]:
            cols = [c.strip() for c in ln.split("|")]
            # cols -> ['', 'date', 'package', 'version', 'import', 'reason', 'notes', '']
            if len(cols) >= 4:
                pkg_spec = cols[2]
                # skip header / separator lines (eg. 'Package (pip)' or '------')
                if not pkg_spec:
                    continue
                if "package (pip)" in pkg_spec.lower():
                    continue
                if set(pkg_spec.strip()) == {"-"}:
                    continue
                packages.append(pkg_spec)
    return packages


def _import_name_from_spec(spec: str) -> str:
    name = spec.split("==")[0].strip()
    # try exact, then lowercase/underscore, then common aliases
    return COMMON_IMPORT_ALIASES.get(name, name)


def check_and_log(strict: bool = False) -> List[str]:
    """Check packages listed in CREATED_DEPENDENCIES.md.

    Returns list of missing packages (package specs).
    If `strict` is True, raises ImportError if any are missing.
    """
    missing: List[str] = []
    packages = _parse_md_packages()

    for spec in packages:
        import_name = _import_name_from_spec(spec)
        tried = []
        ok = False
        # Try direct import
        try:
            importlib.import_module(import_name)
            ok = True
        except Exception as _:
            tried.append(import_name)
            # try with hyphens replaced by underscore
            alt = import_name.replace("-", "_")
            if alt != import_name:
                try:
                    importlib.import_module(alt)
                    ok = True
                except Exception:
                    tried.append(alt)
        if not ok:
            missing.append(spec)
            logger.warning(
                "Missing dependency: %s (tried imports: %s). Install with: pip install %s",
                spec,
                ",".join(tried) or import_name,
                spec,
            )
    if missing and strict:
        raise ImportError("Missing runtime dependencies: %s" % ", ".join(missing))
    return missing
