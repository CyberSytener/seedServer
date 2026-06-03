"""Tests for P7-12: Per-tool permission matrix.

Covers:
  - ToolPermissionConfig loads from dict and YAML
  - Default values for unlisted tools
  - Per-tool flags: requires_confirmation, sandbox_required, allowed_in_sandbox
  - is_tool_allowed() enforces per-tool scope requirement
  - Config missing tools use defaults
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.core.agent.tool_registry import (
    DEFAULT_TOOL_PERMISSION,
    ToolPermissionConfig,
    ToolRegistry,
)
from app.core.blocks import BlockMetadata, BlockRegistry


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture()
def sample_config() -> Dict[str, Any]:
    """Sample tool_permissions dict matching YAML spec."""
    return {
        "defaults": {
            "require_scope": "agent:tools:execute",
            "sandbox_required": False,
            "requires_confirmation": False,
            "allowed_in_sandbox": False,
            "max_calls_per_session": None,
        },
        "tools": {
            "inventory_sync": {
                "require_scope": "agent:tools:execute",
                "sandbox_required": True,
                "allowed_in_sandbox": True,
                "requires_confirmation": True,
                "max_calls_per_session": 5,
            },
            "recipe_generator": {
                "require_scope": "agent:tools:execute",
                "sandbox_required": False,
                "requires_confirmation": False,
            },
            "admin_reset": {
                "require_scope": "admin:tools:execute",
                "sandbox_required": False,
                "requires_confirmation": True,
                "max_calls_per_session": 1,
            },
        },
    }


class DummyBlock:
    pass


@pytest.fixture()
def block_registry() -> BlockRegistry:
    """BlockRegistry with several test blocks."""
    reg = BlockRegistry()
    for name in ("inventory_sync", "recipe_generator", "admin_reset", "unknown_tool"):
        reg.register(
            name, DummyBlock,
            description=f"Test block {name}",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
        )
    return reg


# ===================================================================
# 1. ToolPermissionConfig tests
# ===================================================================

class TestToolPermissionConfig:

    def test_default_empty_config(self):
        cfg = ToolPermissionConfig()
        d = cfg.get("any_tool")
        assert d["requires_confirmation"] is False
        assert d["sandbox_required"] is False
        assert d["allowed_in_sandbox"] is False
        assert d["require_scope"] == "agent:tools:execute"

    def test_load_from_dict(self, sample_config):
        cfg = ToolPermissionConfig(sample_config)
        assert cfg.requires_confirmation("inventory_sync") is True
        assert cfg.sandbox_required("inventory_sync") is True
        assert cfg.allowed_in_sandbox("inventory_sync") is True
        assert cfg.get("inventory_sync")["max_calls_per_session"] == 5

    def test_unlisted_tool_gets_defaults(self, sample_config):
        cfg = ToolPermissionConfig(sample_config)
        assert cfg.requires_confirmation("unknown_tool") is False
        assert cfg.sandbox_required("unknown_tool") is False
        assert cfg.allowed_in_sandbox("unknown_tool") is False

    def test_read_only_tool(self, sample_config):
        cfg = ToolPermissionConfig(sample_config)
        assert cfg.requires_confirmation("recipe_generator") is False
        assert cfg.sandbox_required("recipe_generator") is False

    def test_admin_tool_scope(self, sample_config):
        cfg = ToolPermissionConfig(sample_config)
        assert cfg.require_scope("admin_reset") == "admin:tools:execute"
        assert cfg.requires_confirmation("admin_reset") is True
        assert cfg.get("admin_reset")["max_calls_per_session"] == 1

    def test_from_yaml(self):
        """Load from actual tool_permissions.yaml file."""
        cfg = ToolPermissionConfig.from_yaml()
        # Should have loaded defaults at minimum
        assert cfg.get("anything")["require_scope"] == "agent:tools:execute"
        # inventory_sync should be configured
        assert cfg.requires_confirmation("inventory_sync") is True
        assert cfg.sandbox_required("inventory_sync") is True

    def test_from_yaml_missing_file(self, tmp_path):
        """Missing file returns default config."""
        cfg = ToolPermissionConfig.from_yaml(str(tmp_path / "nonexistent.yaml"))
        assert cfg.requires_confirmation("any") is False

    def test_from_yaml_custom_file(self, tmp_path):
        """Load from a custom YAML file."""
        yaml_content = """
defaults:
  require_scope: "custom:scope"
  sandbox_required: true
tools:
  my_tool:
    requires_confirmation: true
"""
        yaml_file = tmp_path / "perms.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        cfg = ToolPermissionConfig.from_yaml(str(yaml_file))
        assert cfg.require_scope("any") == "custom:scope"
        assert cfg.sandbox_required("any") is True
        assert cfg.requires_confirmation("my_tool") is True


# ===================================================================
# 2. is_tool_allowed() with per-tool scope enforcement
# ===================================================================

class TestIsToolAllowedWithScopes:

    def test_wildcard_scope_allows_all(self, block_registry, sample_config):
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        assert tr.is_tool_allowed("recipe_generator", ["*"]) is True
        assert tr.is_tool_allowed("inventory_sync", ["*"]) is True
        assert tr.is_tool_allowed("admin_reset", ["*"]) is True

    def test_exact_tool_name_with_matching_scope(self, block_registry, sample_config):
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        scopes = ["recipe_generator", "agent:tools:execute"]
        assert tr.is_tool_allowed("recipe_generator", scopes) is True

    def test_tool_name_in_scope_but_missing_required_scope(self, block_registry, sample_config):
        """admin_reset requires 'admin:tools:execute' — normal agent scope is insufficient."""
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        scopes = ["admin_reset", "agent:tools:execute"]
        assert tr.is_tool_allowed("admin_reset", scopes) is False

    def test_admin_tool_with_admin_scope(self, block_registry, sample_config):
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        scopes = ["admin_reset", "admin:tools:execute"]
        assert tr.is_tool_allowed("admin_reset", scopes) is True

    def test_prefix_wildcard_scope(self, block_registry, sample_config):
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        scopes = ["recipe_generator", "agent:*"]
        assert tr.is_tool_allowed("recipe_generator", scopes) is True

    def test_empty_scopes(self, block_registry, sample_config):
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        assert tr.is_tool_allowed("recipe_generator", []) is False

    def test_tool_not_in_registry(self, block_registry, sample_config):
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        assert tr.is_tool_allowed("nonexistent", ["*"]) is False

    def test_unknown_tool_uses_default_scope(self, block_registry, sample_config):
        """unknown_tool is in BlockRegistry but not in tool_permissions — uses default scope."""
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        scopes = ["unknown_tool", "agent:tools:execute"]
        assert tr.is_tool_allowed("unknown_tool", scopes) is True


# ===================================================================
# 3. list_tools_for_llm respects scope enforcement
# ===================================================================

class TestListToolsForLlmWithPermissions:

    def test_wildcard_lists_all(self, block_registry, sample_config):
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        manifests = tr.list_tools_for_llm(["*"])
        names = {m["function"]["name"] for m in manifests}
        assert "recipe_generator" in names
        assert "inventory_sync" in names
        # admin_reset requires admin:tools:execute (not in ["*"]
        # Wait — "*" grants all scopes, so it should be included
        assert "admin_reset" in names

    def test_limited_scope(self, block_registry, sample_config):
        tr = ToolRegistry(block_registry, ToolPermissionConfig(sample_config))
        scopes = ["recipe_generator", "agent:tools:execute"]
        manifests = tr.list_tools_for_llm(scopes)
        names = {m["function"]["name"] for m in manifests}
        assert "recipe_generator" in names
        assert "inventory_sync" not in names  # not in tool scopes list
        assert "admin_reset" not in names
