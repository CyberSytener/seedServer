#!/usr/bin/env python3
"""Generate a UIContextPack JSON from a frontend source directory.

Walks the provided directory tree, extracts component names from
``.tsx`` / ``.vue`` / ``.svelte`` files via regex (not AST), detects
route definitions from common patterns, and outputs JSON matching the
``UIContextPack`` schema.

Usage
-----
    python scripts/generate_ui_context_pack.py \\
        --dir saga-console/src \\
        --framework react \\
        --output context_pack.json

This is a **developer convenience** tool, not a production service.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Component extraction (regex-based, not AST)
# ---------------------------------------------------------------------------

# React / TSX: export default function MyComponent | export const MyComponent
_TSX_COMPONENT_RE = re.compile(
    r"(?:export\s+(?:default\s+)?(?:function|const|class)\s+)"
    r"([A-Z][A-Za-z0-9_]*)",
)

# Vue SFC: <script> block with defineComponent or export default
_VUE_COMPONENT_RE = re.compile(
    r"(?:defineComponent|export\s+default)\s*\(\s*\{[^}]*name:\s*['\"]([A-Za-z0-9_]+)['\"]",
    re.DOTALL,
)

# Svelte: filename IS the component name (convention)
# No regex needed — we use the filename.

# Props: React — interface.*Props { … }
_REACT_PROPS_RE = re.compile(
    r"(?:interface|type)\s+(\w*Props)\s*(?:=\s*)?\{([^}]*)?\}",
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Route extraction
# ---------------------------------------------------------------------------

# React Router: <Route path="/foo" element={<Bar />} />  or { path: "/foo", element: ... }
_REACT_ROUTE_RE = re.compile(
    r"""(?:path\s*[:=]\s*["'])([^"']+)["']""",
)

# Vue Router: { path: '/foo', component: ... }
_VUE_ROUTE_RE = re.compile(
    r"""path\s*:\s*["']([^"']+)["']""",
)


def _extract_components_tsx(path: Path, content: str) -> List[Dict[str, Any]]:
    """Extract React/TSX components from file content."""
    results = []
    for m in _TSX_COMPONENT_RE.finditer(content):
        name = m.group(1)
        comp: Dict[str, Any] = {
            "name": name,
            "path": str(path),
        }
        # Try to extract props interface
        for pm in _REACT_PROPS_RE.finditer(content):
            if pm.group(1).startswith(name) or "Props" in pm.group(1):
                comp["props_schema"] = {"raw": pm.group(0).strip()[:200]}
                break
        results.append(comp)
    return results


def _extract_components_vue(path: Path, content: str) -> List[Dict[str, Any]]:
    """Extract Vue SFC component names."""
    results = []
    for m in _VUE_COMPONENT_RE.finditer(content):
        results.append({"name": m.group(1), "path": str(path)})
    if not results:
        # Fallback: use filename
        name = path.stem
        if name[0].isupper():
            results.append({"name": name, "path": str(path)})
    return results


def _extract_components_svelte(path: Path, content: str) -> List[Dict[str, Any]]:
    """Svelte component = filename."""
    return [{"name": path.stem, "path": str(path)}]


EXTRACTORS = {
    ".tsx": _extract_components_tsx,
    ".jsx": _extract_components_tsx,
    ".vue": _extract_components_vue,
    ".svelte": _extract_components_svelte,
}


def _extract_routes(content: str, framework: str) -> List[Dict[str, Any]]:
    """Extract route paths from file content."""
    regex = _REACT_ROUTE_RE if framework in ("react", "unknown") else _VUE_ROUTE_RE
    seen = set()
    routes = []
    for m in regex.finditer(content):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            routes.append({"path": path, "component": ""})
    return routes


# ---------------------------------------------------------------------------
# Directory walker
# ---------------------------------------------------------------------------

def generate_pack(
    directory: str,
    framework: str = "unknown",
) -> Dict[str, Any]:
    """Walk *directory* and build a UIContextPack dict."""
    root = Path(directory).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    components: List[Dict[str, Any]] = []
    routes: List[Dict[str, Any]] = []
    tree_lines: List[str] = []

    # Determine which extensions to scan
    ext_set = set(EXTRACTORS.keys())

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip node_modules, dist, .git, __pycache__
        dirnames[:] = [
            d for d in dirnames
            if d not in {"node_modules", "dist", ".git", "__pycache__", ".next", "build"}
        ]
        rel_dir = Path(dirpath).relative_to(root)
        for fn in sorted(filenames):
            fpath = Path(dirpath) / fn
            rel_path = rel_dir / fn
            tree_lines.append(str(rel_path))

            ext = fpath.suffix
            if ext not in ext_set:
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            extractor = EXTRACTORS.get(ext)
            if extractor:
                for comp in extractor(rel_path, content):
                    components.append(comp)

            # Check for route definitions in files that look like route configs
            lower_fn = fn.lower()
            if any(kw in lower_fn for kw in ("route", "router", "app")):
                routes.extend(_extract_routes(content, framework))

    # Build raw tree (truncate to 50KB)
    raw_tree = "\n".join(tree_lines)
    if len(raw_tree.encode("utf-8")) > 50 * 1024:
        raw_tree = raw_tree[:50 * 1024]

    # Cap components at 200
    if len(components) > 200:
        components = components[:200]

    return {
        "source": str(root),
        "framework": framework,
        "components": components,
        "routes": routes,
        "contracts": [],
        "raw_tree": raw_tree if tree_lines else None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a UIContextPack JSON from a frontend source directory.",
    )
    parser.add_argument(
        "--dir", required=True,
        help="Path to the frontend source directory (e.g. saga-console/src)",
    )
    parser.add_argument(
        "--framework", default="unknown",
        choices=["react", "vue", "svelte", "unknown"],
        help="UI framework (default: unknown)",
    )
    parser.add_argument(
        "--output", default="-",
        help="Output file path, or '-' for stdout (default: stdout)",
    )
    args = parser.parse_args()

    pack = generate_pack(args.dir, args.framework)

    # Validate via Pydantic model (optional — only if app package is importable)
    try:
        from app.core.agent.ui_context import UIContextPack
        validated = UIContextPack(**pack)
        output = validated.model_dump_json(indent=2)
    except ImportError:
        output = json.dumps(pack, indent=2)

    if args.output == "-":
        print(output)
    else:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Wrote {len(output)} bytes to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
