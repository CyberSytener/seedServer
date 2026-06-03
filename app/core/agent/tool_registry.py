"""ToolRegistry — agent-facing tool catalog wrapping BlockRegistry (Phase 7 — P7-04).

ToolRegistry is the **catalog/manifest** layer. It does NOT execute tools.
All execution goes through ``ActionRouter.execute_action()``.

Responsibilities:
- ``list_tools_for_llm(session_scopes)`` — default-deny: only allowlisted tools visible
- ``get_tool_manifest(name)`` — single tool manifest
- ``is_tool_allowed(name, session_scopes)`` — checks allowlist + per-tool config
- ``validate_tool_input(name, inputs)`` — validates against INPUT_SCHEMA
- ``build_action(name, inputs, session_id, user_id)`` — bridges to ActionRouter
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.core.blocks import BlockMetadata, BlockRegistry
from app.models.realtime.actions import Action, ActionMetadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool permission config (loaded from dict / YAML)
# ---------------------------------------------------------------------------

DEFAULT_TOOL_PERMISSION = {
    "require_scope": "agent:tools:execute",
    "sandbox_required": False,
    "requires_confirmation": False,
    "allowed_in_sandbox": False,
    "max_calls_per_session": None,
}


class ToolPermissionConfig:
    """Loaded tool_permissions configuration — default-deny for agent visibility."""

    # Default YAML location (relative to project root)
    DEFAULT_YAML_PATH = Path(__file__).parent / "tool_permissions.yaml"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        raw = config or {}
        self._defaults = {**DEFAULT_TOOL_PERMISSION, **(raw.get("defaults") or {})}
        self._tools: Dict[str, Dict[str, Any]] = {}
        for tool_name, tool_cfg in (raw.get("tools") or {}).items():
            merged = {**self._defaults, **tool_cfg}
            self._tools[tool_name] = merged

    @classmethod
    def from_yaml(cls, path: Optional[str] = None) -> "ToolPermissionConfig":
        """Load tool permissions from a YAML file.

        Falls back to ``DEFAULT_YAML_PATH`` if *path* is ``None``.
        Returns default config if file doesn't exist.
        """
        yaml_path = Path(path) if path else cls.DEFAULT_YAML_PATH
        if not yaml_path.is_file():
            logger.info("tool_permissions.yaml not found at %s — using defaults", yaml_path)
            return cls()
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            return cls(raw)
        except Exception:
            logger.warning("Failed to parse tool_permissions.yaml at %s", yaml_path, exc_info=True)
            return cls()

    def get(self, tool_name: str) -> Dict[str, Any]:
        return self._tools.get(tool_name, dict(self._defaults))

    def requires_confirmation(self, tool_name: str) -> bool:
        return bool(self.get(tool_name).get("requires_confirmation", False))

    def sandbox_required(self, tool_name: str) -> bool:
        return bool(self.get(tool_name).get("sandbox_required", False))

    def allowed_in_sandbox(self, tool_name: str) -> bool:
        return bool(self.get(tool_name).get("allowed_in_sandbox", False))

    def require_scope(self, tool_name: str) -> str:
        return str(self.get(tool_name).get("require_scope", "agent:tools:execute"))


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Agent-facing tool catalog wrapping ``BlockRegistry``.

    Default-deny: only tools explicitly listed in ``session.tool_scopes`` are
    visible to the LLM. ``tool_scopes: ["*"]`` exposes all registered tools
    (admin only).
    """

    def __init__(
        self,
        block_registry: BlockRegistry,
        permissions: Optional[ToolPermissionConfig] = None,
    ) -> None:
        self._block_registry = block_registry
        self._permissions = permissions or ToolPermissionConfig()

    # ------------------------------------------------------------------
    # Allowlist check
    # ------------------------------------------------------------------

    def is_tool_allowed(self, name: str, session_scopes: List[str]) -> bool:
        """Check if *name* is in the session allowlist, exists in BlockRegistry,
        and the session has the required per-tool scope.

        The default scope (``agent:tools:execute``) is implicitly satisfied when
        the tool name is explicitly in ``session_scopes``. Only elevated/custom
        scopes (e.g. ``admin:tools:execute``) require an explicit scope grant.
        """
        if not session_scopes:
            return False
        # Must exist in block registry
        if name not in self._block_registry.list_blocks():
            return False
        # Session scope check: exact name match or wildcard
        if "*" not in session_scopes and name not in session_scopes:
            return False
        # Per-tool scope check — only enforced for non-default scopes
        required_scope = self._permissions.require_scope(name)
        default_scope = DEFAULT_TOOL_PERMISSION["require_scope"]
        if required_scope != default_scope:
            if not self._scope_matches(required_scope, session_scopes):
                return False
        return True

    @staticmethod
    def _scope_matches(required: str, scopes: List[str]) -> bool:
        """Check if *required* scope is satisfied by *scopes*.

        Supports wildcard ``*`` and prefix wildcards like ``agent:*``.
        """
        if "*" in scopes:
            return True
        if required in scopes:
            return True
        # Check prefix wildcards: "agent:*" matches "agent:tools:execute"
        for s in scopes:
            if s.endswith(":*"):
                prefix = s[:-1]  # "agent:"
                if required.startswith(prefix):
                    return True
        return False

    # ------------------------------------------------------------------
    # Manifests (for LLM function-calling)
    # ------------------------------------------------------------------

    def list_tools_for_llm(self, session_scopes: List[str]) -> List[Dict[str, Any]]:
        """Return OpenAI function-calling-compatible tool manifests for allowed tools.

        Default-deny: if ``session_scopes`` is empty, returns ``[]``.
        Only tools in the allowlist are visible.
        """
        if not session_scopes:
            return []

        manifests: List[Dict[str, Any]] = []
        all_blocks = self._block_registry.list_blocks()

        for block_name in all_blocks:
            if not self.is_tool_allowed(block_name, session_scopes):
                continue
            try:
                meta = self._block_registry.get_metadata(block_name)
            except ValueError:
                continue
            manifests.append(self._metadata_to_manifest(meta))

        return manifests

    def get_tool_manifest(self, name: str) -> Dict[str, Any]:
        """Single tool manifest. Raises ``ValueError`` if not found."""
        meta = self._block_registry.get_metadata(name)
        return self._metadata_to_manifest(meta)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_tool_input(self, name: str, inputs: Dict[str, Any]) -> bool:
        """Basic validation of inputs against ``INPUT_SCHEMA``.

        Checks required fields are present. Full JSON Schema validation
        can be added later.
        """
        try:
            meta = self._block_registry.get_metadata(name)
        except ValueError:
            return False
        schema = meta.input_schema or {}
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in inputs:
                return False
        return True

    # ------------------------------------------------------------------
    # Action builder (bridge to ActionRouter)
    # ------------------------------------------------------------------

    def build_action(
        self,
        name: str,
        inputs: Dict[str, Any],
        *,
        session_id: str = "",
        user_id: Optional[str] = None,
    ) -> Action:
        """Build an ``Action`` object suitable for ``ActionRouter.execute_action()``.

        This is the bridge between ToolRegistry manifests and ActionRouter execution.
        """
        action_id = f"agent_tool_{uuid.uuid4().hex[:12]}"
        return Action(
            name=name,
            id=action_id,
            params=inputs,
            metadata=ActionMetadata(
                session_id=session_id,
                user_id=user_id,
                requires_user_confirmation=self._permissions.requires_confirmation(name),
                audit_tags=["agent_tool_call"],
            ),
        )

    # ------------------------------------------------------------------
    # Permission config accessors
    # ------------------------------------------------------------------

    @property
    def permissions(self) -> ToolPermissionConfig:
        return self._permissions

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata_to_manifest(meta: BlockMetadata) -> Dict[str, Any]:
        """Convert ``BlockMetadata`` to an OpenAI function-calling manifest."""
        return {
            "type": "function",
            "function": {
                "name": meta.name,
                "description": meta.description or "",
                "parameters": meta.input_schema or {"type": "object", "properties": {}},
            },
        }
