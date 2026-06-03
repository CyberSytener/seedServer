"""Tests for router_registration.py — verify only ImportError is suppressed.

T-1 policy: unexpected exceptions during optional router imports must
propagate (not be swallowed), so startup failures are visible.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

ROUTER_REG_PATH = Path(__file__).resolve().parents[2] / "app" / "infrastructure" / "router_registration.py"


class TestRouterRegistrationExceptionPolicy:
    """Verify that router_registration.py only catches ImportError."""

    def test_no_broad_except_exception(self) -> None:
        """No bare ``except Exception`` handlers should exist."""
        source = ROUTER_REG_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        broad_catches: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # ExceptHandler.type is None for bare `except:`,
                # or an ast.Name / ast.Tuple for typed catches.
                if node.type is None:
                    broad_catches.append(node.lineno)
                elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    broad_catches.append(node.lineno)

        assert broad_catches == [], (
            f"Broad 'except Exception' found at lines {broad_catches}. "
            "Policy: only ImportError/ModuleNotFoundError should be suppressed."
        )

    def test_import_error_catches_present(self) -> None:
        """There should still be ImportError catches for optional imports."""
        source = ROUTER_REG_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        import_error_catches = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is not None:
                if isinstance(node.type, ast.Name) and node.type.id == "ImportError":
                    import_error_catches += 1

        assert import_error_catches >= 15, (
            f"Expected at least 15 ImportError catches, found {import_error_catches}"
        )

    def test_file_is_valid_python(self) -> None:
        """Sanity check: the file should parse without errors."""
        source = ROUTER_REG_PATH.read_text(encoding="utf-8")
        ast.parse(source)  # Raises SyntaxError on failure
