"""Repo context pack — GitHub repo content for agent LLM prompts (P0-30).

Mirrors the ``UIContextPack`` pattern: a structured payload that gets
serialized as a ``MessageRole.CONTEXT`` message in the session history,
then formatted into the LLM prompt via ``to_prompt_section()``.

Size limits:
  • Max total content across all files: 200 KB.
  • Max individual file entries: 50.
  • Max tree string: 50 KB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TOTAL_CONTENT_BYTES = 200 * 1024  # 200 KB
MAX_FILE_ENTRIES = 50
MAX_TREE_BYTES = 50 * 1024  # 50 KB
PROMPT_FILE_LIMIT = 30  # files shown in prompt
PROMPT_TREE_CHARS = 3000  # tree chars shown in prompt


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RepoFile:
    """A single file fetched from a repository."""

    path: str
    content: str
    language: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "content": self.content, "language": self.language}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepoFile":
        return cls(
            path=str(data.get("path", "")),
            content=str(data.get("content", "")),
            language=str(data.get("language", "")),
        )


@dataclass
class RepoContextPack:
    """Structured repository context for injection into agent prompts.

    Follows the same lifecycle as ``UIContextPack``:
    1. Client (or github_fetch block) pushes repo context.
    2. Stored as a ``MessageRole.CONTEXT`` message (subtype ``repo``).
    3. Retrieved and formatted on prompt-build via ``to_prompt_section()``.
    """

    repo_url: str
    files: List[RepoFile] = field(default_factory=list)
    tree: Optional[str] = None
    fetched_at: str = ""  # ISO-8601 string

    def __post_init__(self) -> None:
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()
        self.validate()

    # ----- Validation --------------------------------------------------

    def validate(self) -> None:
        """Raise ``ValueError`` if limits are exceeded."""
        if not self.repo_url:
            raise ValueError("repo_url is required")

        if len(self.files) > MAX_FILE_ENTRIES:
            raise ValueError(
                f"Too many files: {len(self.files)} (max {MAX_FILE_ENTRIES})"
            )

        total = sum(len(f.content.encode("utf-8", errors="replace")) for f in self.files)
        if total > MAX_TOTAL_CONTENT_BYTES:
            raise ValueError(
                f"Total file content too large: {total} bytes (max {MAX_TOTAL_CONTENT_BYTES})"
            )

        if self.tree and len(self.tree.encode("utf-8", errors="replace")) > MAX_TREE_BYTES:
            raise ValueError(
                f"Tree too large: {len(self.tree)} chars (max {MAX_TREE_BYTES} bytes)"
            )

    # ----- Serialization -----------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "repo",
            "repo_url": self.repo_url,
            "files": [f.to_dict() for f in self.files],
            "tree": self.tree,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepoContextPack":
        files = [RepoFile.from_dict(f) for f in (data.get("files") or [])]
        return cls(
            repo_url=str(data.get("repo_url", "")),
            files=files,
            tree=data.get("tree"),
            fetched_at=str(data.get("fetched_at", "")),
        )

    # ----- Prompt formatting -------------------------------------------

    def to_prompt_section(self) -> str:
        """Format this pack as a text block suitable for the LLM prompt."""
        lines: List[str] = []
        lines.append("=== Repository Context ===")
        lines.append(f"Repo: {self.repo_url}")
        lines.append(f"Fetched: {self.fetched_at}")

        if self.tree:
            tree_str = self.tree[:PROMPT_TREE_CHARS]
            if len(self.tree) > PROMPT_TREE_CHARS:
                tree_str += "\n  ... (truncated)"
            lines.append(f"\nFile tree:\n{tree_str}")

        shown = self.files[:PROMPT_FILE_LIMIT]
        if shown:
            lines.append(f"\nFiles ({len(self.files)} total, showing {len(shown)}):")
            for f in shown:
                lang_tag = f" [{f.language}]" if f.language else ""
                lines.append(f"\n--- {f.path}{lang_tag} ---")
                lines.append(f.content)

            if len(self.files) > PROMPT_FILE_LIMIT:
                omitted = len(self.files) - PROMPT_FILE_LIMIT
                lines.append(f"\n... {omitted} more file(s) available via github_fetch tool.")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session-level file cache
# ---------------------------------------------------------------------------


class RepoFileCache:
    """In-memory cache of fetched files for a single agent session.

    Prevents re-fetching the same URL within one session. Enforces the
    global 200 KB content limit across all cached files.
    """

    def __init__(self, max_bytes: int = MAX_TOTAL_CONTENT_BYTES) -> None:
        self._max_bytes = max_bytes
        self._files: Dict[str, RepoFile] = {}  # keyed by URL or path
        self._total_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def count(self) -> int:
        return len(self._files)

    def get(self, key: str) -> Optional[RepoFile]:
        """Return cached file or ``None``."""
        return self._files.get(key)

    def has(self, key: str) -> bool:
        return key in self._files

    def put(self, key: str, file: RepoFile) -> bool:
        """Add a file to the cache. Returns False if it would exceed limits."""
        size = len(file.content.encode("utf-8", errors="replace"))
        if key in self._files:
            # Replace — subtract old size first
            old = self._files[key]
            self._total_bytes -= len(old.content.encode("utf-8", errors="replace"))

        if self._total_bytes + size > self._max_bytes:
            return False

        self._files[key] = file
        self._total_bytes += size
        return True

    def all_files(self) -> List[RepoFile]:
        return list(self._files.values())

    def to_pack(self, repo_url: str, tree: Optional[str] = None) -> RepoContextPack:
        """Build a ``RepoContextPack`` from all cached files."""
        return RepoContextPack(
            repo_url=repo_url,
            files=self.all_files(),
            tree=tree,
        )
