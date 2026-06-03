"""UI context pack model and validation (Phase 7 — P7-08).

The client (frontend or CLI) pushes a UI context snapshot to the server.
The server stores it per-session and makes it available to the agent loop.

This is **push-based** — the client is responsible for generating the pack.
Server-side repo indexing is out of scope for Phase 7.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------

MAX_PAYLOAD_BYTES = 100 * 1024   # 100 KB total
MAX_COMPONENTS = 200
MAX_RAW_TREE_BYTES = 50 * 1024   # 50 KB raw_tree


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class UIComponent(BaseModel):
    """A single UI component extracted from the frontend codebase."""

    name: str
    path: str = ""
    props_schema: Optional[Dict[str, Any]] = None
    slots: Optional[List[str]] = None


class UIRoute(BaseModel):
    """A frontend route definition."""

    path: str
    component: str = ""
    layout: Optional[str] = None


class UIContract(BaseModel):
    """An API contract or type definition used by the UI."""

    name: str
    contract_schema: Optional[str] = None


# ---------------------------------------------------------------------------
# Main model
# ---------------------------------------------------------------------------

class UIContextPack(BaseModel):
    """Snapshot of frontend/UI context pushed by the client.

    Validated constraints:
      - ``components`` list max 200 entries
      - ``raw_tree`` max 50 KB
      - Total serialized payload max 100 KB
    """

    source: str = Field(
        ...,
        description="Repo path or URL the pack was generated from",
    )
    framework: str = Field(
        default="unknown",
        description="UI framework: react | vue | svelte | unknown",
    )
    components: List[UIComponent] = Field(
        default_factory=list,
        description="Extracted component definitions (max 200)",
    )
    routes: List[UIRoute] = Field(
        default_factory=list,
        description="Extracted route definitions",
    )
    contracts: List[UIContract] = Field(
        default_factory=list,
        description="API contracts / type schemas",
    )
    raw_tree: Optional[str] = Field(
        default=None,
        description="Full file-tree string (max 50 KB)",
    )

    @field_validator("framework")
    @classmethod
    def validate_framework(cls, v: str) -> str:
        allowed = {"react", "vue", "svelte", "unknown"}
        if v not in allowed:
            raise ValueError(f"framework must be one of {allowed}, got '{v}'")
        return v

    @field_validator("components")
    @classmethod
    def validate_component_count(cls, v: List[UIComponent]) -> List[UIComponent]:
        if len(v) > MAX_COMPONENTS:
            raise ValueError(
                f"Too many components: {len(v)} exceeds max {MAX_COMPONENTS}"
            )
        return v

    @field_validator("raw_tree")
    @classmethod
    def validate_raw_tree_size(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v.encode("utf-8")) > MAX_RAW_TREE_BYTES:
            raise ValueError(
                f"raw_tree exceeds max size of {MAX_RAW_TREE_BYTES} bytes"
            )
        return v

    @model_validator(mode="after")
    def validate_total_size(self) -> "UIContextPack":
        payload_bytes = len(self.model_dump_json().encode("utf-8"))
        if payload_bytes > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"Total payload size {payload_bytes} bytes exceeds max "
                f"{MAX_PAYLOAD_BYTES} bytes"
            )
        return self

    def to_prompt_section(self) -> str:
        """Format the context pack as a text section for the LLM prompt."""
        parts = [
            f"[UI Context — {self.framework} from {self.source}]",
        ]
        if self.components:
            comp_names = [c.name for c in self.components[:50]]
            parts.append(f"Components ({len(self.components)} total): {', '.join(comp_names)}")
        if self.routes:
            route_paths = [r.path for r in self.routes[:30]]
            parts.append(f"Routes ({len(self.routes)} total): {', '.join(route_paths)}")
        if self.contracts:
            contract_names = [c.name for c in self.contracts[:20]]
            parts.append(f"Contracts: {', '.join(contract_names)}")
        if self.raw_tree:
            # Truncate for prompt if very large
            tree_preview = self.raw_tree[:2000]
            if len(self.raw_tree) > 2000:
                tree_preview += "\n… (truncated)"
            parts.append(f"File tree:\n{tree_preview}")
        return "\n".join(parts)
