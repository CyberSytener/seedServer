"""Tests for ToolRegistry — Phase 7 P7-04.

Validates:
- Default-deny: list_tools_for_llm([]) returns empty
- Allowlist: list_tools_for_llm(["recipe_generator"]) returns exactly 1 manifest
- is_tool_allowed rejects non-allowlisted tools
- Wildcard: ["*"] exposes all registered tools
- build_action() produces a valid Action
- validate_tool_input() checks required fields
- Non-existent tool → error
"""

from __future__ import annotations

import pytest

from app.core.blocks import BlockBase, BlockMetadata, BlockRegistry
from app.core.agent.tool_registry import ToolPermissionConfig, ToolRegistry


# ---------------------------------------------------------------------------
# Fixtures: minimal BlockRegistry with two stub blocks
# ---------------------------------------------------------------------------

class StubRecipeGenerator(BlockBase):
    DESCRIPTION = "Generate a recipe from ingredients"
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "ingredients": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["ingredients"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {"recipe": {"type": "string"}},
    }

    async def execute(self, context, inputs):
        return {"recipe": "stub_recipe"}


class StubInventorySync(BlockBase):
    DESCRIPTION = "Sync inventory from external source"
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "source_id": {"type": "string"},
        },
        "required": ["source_id"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {"synced_count": {"type": "integer"}},
    }

    async def execute(self, context, inputs):
        return {"synced_count": 0}


class StubSecretTool(BlockBase):
    DESCRIPTION = "A tool that should not be visible to most agents"
    INPUT_SCHEMA = {"type": "object", "properties": {}}
    OUTPUT_SCHEMA = {"type": "object", "properties": {}}

    async def execute(self, context, inputs):
        return {}


@pytest.fixture()
def block_registry():
    reg = BlockRegistry()
    reg.register("recipe_generator", StubRecipeGenerator)
    reg.register("inventory_sync", StubInventorySync)
    reg.register("secret_tool", StubSecretTool)
    return reg


@pytest.fixture()
def permissions():
    return ToolPermissionConfig({
        "defaults": {
            "require_scope": "agent:tools:execute",
            "sandbox_required": False,
            "requires_confirmation": False,
            "allowed_in_sandbox": False,
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
        },
    })


@pytest.fixture()
def registry(block_registry, permissions):
    return ToolRegistry(block_registry, permissions)


# ---------------------------------------------------------------------------
# Default-deny tests
# ---------------------------------------------------------------------------

class TestDefaultDeny:
    def test_empty_scopes_returns_no_manifests(self, registry):
        manifests = registry.list_tools_for_llm([])
        assert manifests == []

    def test_single_scope_returns_only_that_tool(self, registry):
        manifests = registry.list_tools_for_llm(["recipe_generator"])
        assert len(manifests) == 1
        assert manifests[0]["function"]["name"] == "recipe_generator"

    def test_non_allowlisted_tool_invisible(self, registry):
        manifests = registry.list_tools_for_llm(["recipe_generator"])
        names = [m["function"]["name"] for m in manifests]
        assert "secret_tool" not in names
        assert "inventory_sync" not in names

    def test_wildcard_exposes_all_tools(self, registry):
        manifests = registry.list_tools_for_llm(["*"])
        names = {m["function"]["name"] for m in manifests}
        assert "recipe_generator" in names
        assert "inventory_sync" in names
        assert "secret_tool" in names
        assert len(manifests) == 3


# ---------------------------------------------------------------------------
# is_tool_allowed
# ---------------------------------------------------------------------------

class TestIsToolAllowed:
    def test_allowed_tool(self, registry):
        assert registry.is_tool_allowed("recipe_generator", ["recipe_generator"]) is True

    def test_disallowed_tool(self, registry):
        assert registry.is_tool_allowed("secret_tool", ["recipe_generator"]) is False

    def test_nonexistent_tool(self, registry):
        assert registry.is_tool_allowed("nonexistent", ["*"]) is False

    def test_empty_scopes(self, registry):
        assert registry.is_tool_allowed("recipe_generator", []) is False

    def test_wildcard_allows_existing(self, registry):
        assert registry.is_tool_allowed("secret_tool", ["*"]) is True


# ---------------------------------------------------------------------------
# Manifest structure
# ---------------------------------------------------------------------------

class TestManifestStructure:
    def test_manifest_has_openai_format(self, registry):
        manifests = registry.list_tools_for_llm(["recipe_generator"])
        m = manifests[0]
        assert m["type"] == "function"
        assert "function" in m
        func = m["function"]
        assert func["name"] == "recipe_generator"
        assert func["description"] == "Generate a recipe from ingredients"
        assert "properties" in func["parameters"]
        assert "ingredients" in func["parameters"]["properties"]

    def test_get_tool_manifest_single(self, registry):
        m = registry.get_tool_manifest("recipe_generator")
        assert m["function"]["name"] == "recipe_generator"

    def test_get_tool_manifest_nonexistent_raises(self, registry):
        with pytest.raises(ValueError, match="Unknown block type"):
            registry.get_tool_manifest("nonexistent")


# ---------------------------------------------------------------------------
# validate_tool_input
# ---------------------------------------------------------------------------

class TestValidateToolInput:
    def test_valid_input(self, registry):
        assert registry.validate_tool_input("recipe_generator", {"ingredients": ["tomato"]}) is True

    def test_missing_required_field(self, registry):
        assert registry.validate_tool_input("recipe_generator", {}) is False

    def test_nonexistent_tool(self, registry):
        assert registry.validate_tool_input("nonexistent", {}) is False


# ---------------------------------------------------------------------------
# build_action
# ---------------------------------------------------------------------------

class TestBuildAction:
    def test_build_action_produces_valid_action(self, registry):
        action = registry.build_action(
            "recipe_generator",
            {"ingredients": ["tomato", "basil"]},
            session_id="sess-001",
            user_id="user-1",
        )
        assert action.name == "recipe_generator"
        assert action.params["ingredients"] == ["tomato", "basil"]
        assert action.metadata.session_id == "sess-001"
        assert action.metadata.user_id == "user-1"
        assert action.id.startswith("agent_tool_")
        assert "agent_tool_call" in action.metadata.audit_tags

    def test_build_action_confirmation_flag_reflects_permissions(self, registry):
        # recipe_generator: requires_confirmation=False
        a1 = registry.build_action("recipe_generator", {})
        assert a1.metadata.requires_user_confirmation is False

        # inventory_sync: requires_confirmation=True
        a2 = registry.build_action("inventory_sync", {"source_id": "ext-1"})
        assert a2.metadata.requires_user_confirmation is True


# ---------------------------------------------------------------------------
# ToolPermissionConfig
# ---------------------------------------------------------------------------

class TestToolPermissionConfig:
    def test_configured_tool(self, permissions):
        assert permissions.requires_confirmation("inventory_sync") is True
        assert permissions.sandbox_required("inventory_sync") is True
        assert permissions.allowed_in_sandbox("inventory_sync") is True

    def test_unconfigured_tool_uses_defaults(self, permissions):
        assert permissions.requires_confirmation("secret_tool") is False
        assert permissions.sandbox_required("secret_tool") is False
        assert permissions.allowed_in_sandbox("secret_tool") is False

    def test_empty_config(self):
        cfg = ToolPermissionConfig()
        assert cfg.requires_confirmation("any") is False
        assert cfg.require_scope("any") == "agent:tools:execute"
