"""
File-based persona prompt loader with caching and fallback tracking.

Loads persona system prompts from markdown files in prompts/personas/
Provides validation, fallback logic, and development hot-reload support.
Supports optional YAML frontmatter for persona metadata.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# Persona ID validation pattern: only lowercase alphanumeric, underscore, hyphen
PERSONA_ID_PATTERN = re.compile(r'^[a-z0-9_-]{1,64}$')

# Default persona when none specified or unknown personaId
DEFAULT_PERSONA_ID = "classic_tutor"

# Hardcoded fallback prompt in case files are missing (production safety)
FALLBACK_PROMPT = """You are a helpful, knowledgeable assistant. Answer questions clearly and concisely.
Be direct and informative. Focus on providing accurate, useful information."""


@dataclass(frozen=True)
class PersonaResult:
    """Result of persona resolution with fallback tracking."""
    persona_id_used: str
    prompt_text: str
    fallback_reason: Optional[str]  # null, "missing_persona_id", "invalid_persona_id", "unknown_persona_id"


@dataclass(frozen=True)
class PersonaMetadata:
    """Metadata for a persona (parsed from YAML frontmatter or defaults)."""
    id: str
    name: str
    description: str
    tags: list[str]
    prompt_source: str  # "file" or "builtin_fallback"
    prompt_updated_at: Optional[str]  # ISO 8601 timestamp
    is_default: bool


class PersonaPromptLoader:
    """
    Loads persona prompts from markdown files with caching.
    
    In production: loads once at startup and caches in memory.
    In development: reloads files if mtime changed (hot-reload).
    """
    
    def __init__(self, base_dir: str | Path, dev_mode: bool = False):
        self.base_dir = Path(base_dir)
        self.dev_mode = dev_mode
        self._cache: dict[str, str] = {}  # persona_id -> prompt_text
        self._mtime_cache: dict[str, float] = {}  # persona_id -> file mtime
        
        # Ensure directory exists
        if not self.base_dir.exists():
            logging.warning(f"Persona prompts directory not found: {self.base_dir}")
            self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Pre-load all prompts in production mode
        if not dev_mode:
            self._load_all_prompts()
    
    def _load_all_prompts(self) -> None:
        """Load all .md files from personas directory into cache."""
        if not self.base_dir.exists():
            logging.error(f"Cannot load prompts: directory missing: {self.base_dir}")
            return
        
        for file_path in self.base_dir.glob("*.md"):
            persona_id = file_path.stem
            if self._validate_persona_id(persona_id):
                try:
                    prompt_text = file_path.read_text(encoding="utf-8").strip()
                    self._cache[persona_id] = prompt_text
                    self._mtime_cache[persona_id] = file_path.stat().st_mtime
                    logging.info(f"Loaded persona prompt: {persona_id}")
                except Exception as e:
                    logging.error(f"Failed to load persona {persona_id}: {e}")
    
    def _validate_persona_id(self, persona_id: str | None) -> bool:
        """Validate persona ID format for security."""
        if not persona_id:
            return False
        return bool(PERSONA_ID_PATTERN.match(persona_id))
    
    def _parse_frontmatter(self, content: str) -> tuple[Optional[dict], str]:
        """
        Parse YAML frontmatter from markdown content.
        
        Expected format:
        ---
        name: Persona Name
        description: Persona description
        tags: [tag1, tag2]
        ---
        <prompt text>
        
        Returns:
            Tuple of (metadata_dict, prompt_text)
        """
        if not content.startswith("---"):
            return None, content
        
        try:
            # Find the closing ---
            parts = content.split("---", 2)
            if len(parts) < 3:
                return None, content
            
            frontmatter = parts[1].strip()
            prompt_text = parts[2].strip()
            
            metadata = yaml.safe_load(frontmatter)
            return metadata, prompt_text
        except Exception as e:
            logging.warning(f"Failed to parse YAML frontmatter: {e}")
            return None, content
    
    def _load_prompt(self, persona_id: str) -> Optional[str]:
        """
        Load a single prompt from file with caching.
        
        In dev mode: checks mtime and reloads if changed.
        In prod mode: uses in-memory cache.
        """
        file_path = self.base_dir / f"{persona_id}.md"
        
        if not file_path.exists():
            return None
        
        # Dev mode: check mtime for hot-reload
        if self.dev_mode:
            try:
                current_mtime = file_path.stat().st_mtime
                cached_mtime = self._mtime_cache.get(persona_id, 0)
                
                # Reload if file changed or not in cache
                if persona_id not in self._cache or current_mtime > cached_mtime:
                    prompt_text = file_path.read_text(encoding="utf-8").strip()
                    self._cache[persona_id] = prompt_text
                    self._mtime_cache[persona_id] = current_mtime
                    logging.info(f"Hot-reloaded persona prompt: {persona_id}")
            except Exception as e:
                logging.error(f"Failed to reload persona {persona_id}: {e}")
                # Fall through to use cached version if available
        
        return self._cache.get(persona_id)
    
    def get_persona_prompt(self, persona_id_requested: str | None) -> PersonaResult:
        """
        Resolve persona and return prompt with fallback tracking.
        
        Args:
            persona_id_requested: Requested persona identifier (can be None)
            
        Returns:
            PersonaResult with persona_id_used, prompt_text, and fallback_reason
        """
        # Case 1: No persona requested
        if not persona_id_requested:
            return self._get_default_persona("missing_persona_id")
        
        # Case 2: Invalid persona ID format
        if not self._validate_persona_id(persona_id_requested):
            logging.warning(f"Invalid persona ID format: {persona_id_requested}")
            return self._get_default_persona("invalid_persona_id")
        
        # Case 3: Try to load requested persona
        prompt_text = self._load_prompt(persona_id_requested)
        
        if prompt_text:
            # Success: no fallback
            return PersonaResult(
                persona_id_used=persona_id_requested,
                prompt_text=prompt_text,
                fallback_reason=None
            )
        else:
            # Case 4: Persona file not found
            logging.warning(f"Unknown persona ID: {persona_id_requested}")
            return self._get_default_persona("unknown_persona_id")
    
    def _get_default_persona(self, fallback_reason: str) -> PersonaResult:
        """Get default persona with fallback reason."""
        prompt_text = self._load_prompt(DEFAULT_PERSONA_ID)
        
        # Ultimate fallback: use hardcoded prompt if file missing
        if not prompt_text:
            logging.error(f"Default persona file missing: {DEFAULT_PERSONA_ID}.md, using hardcoded fallback")
            prompt_text = FALLBACK_PROMPT
        
        return PersonaResult(
            persona_id_used=DEFAULT_PERSONA_ID,
            prompt_text=prompt_text,
            fallback_reason=fallback_reason
        )
    
    def list_available_personas(self) -> list[str]:
        """Return list of available persona IDs."""
        if not self.base_dir.exists():
            return []
        
        personas = []
        for file_path in self.base_dir.glob("*.md"):
            persona_id = file_path.stem
            if self._validate_persona_id(persona_id):
                personas.append(persona_id)
        
        return sorted(personas)
    
    def get_persona_metadata(self, persona_id: str) -> Optional[PersonaMetadata]:
        """
        Get metadata for a specific persona.
        
        Returns PersonaMetadata with parsed frontmatter or defaults.
        Returns None if persona file doesn't exist.
        """
        file_path = self.base_dir / f"{persona_id}.md"
        
        if not file_path.exists():
            return None
        
        try:
            content = file_path.read_text(encoding="utf-8")
            metadata_dict, _ = self._parse_frontmatter(content)
            
            # Get file modification time
            mtime = file_path.stat().st_mtime
            updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            
            # Extract metadata with defaults
            if metadata_dict:
                name = metadata_dict.get("name", self._format_name(persona_id))
                description = metadata_dict.get("description", "")
                tags = metadata_dict.get("tags", [])
                if isinstance(tags, str):
                    tags = [t.strip() for t in tags.split(",")]
            else:
                # No frontmatter, use defaults
                name = self._format_name(persona_id)
                description = ""
                tags = []
            
            return PersonaMetadata(
                id=persona_id,
                name=name,
                description=description,
                tags=tags,
                prompt_source="file",
                prompt_updated_at=updated_at,
                is_default=(persona_id == DEFAULT_PERSONA_ID)
            )
        except Exception as e:
            logging.error(f"Failed to get metadata for {persona_id}: {e}")
            return None
    
    def _format_name(self, persona_id: str) -> str:
        """Convert persona_id to readable name (e.g., 'bard_cat' -> 'Bard Cat')."""
        return " ".join(word.capitalize() for word in persona_id.replace("-", "_").split("_"))
    
    def list_all_metadata(self) -> list[PersonaMetadata]:
        """Get metadata for all available personas."""
        personas = []
        for persona_id in self.list_available_personas():
            metadata = self.get_persona_metadata(persona_id)
            if metadata:
                personas.append(metadata)
        return personas


# Global loader instance (initialized in main.py)
_loader: Optional[PersonaPromptLoader] = None


def init_persona_loader(base_dir: str | Path, dev_mode: bool = False) -> None:
    """Initialize the global persona loader."""
    global _loader
    _loader = PersonaPromptLoader(base_dir, dev_mode)


def get_persona_prompt(persona_id_requested: str | None) -> PersonaResult:
    """
    Get persona prompt using the global loader.
    
    This is the main API function used by the rest of the application.
    """
    if _loader is None:
        raise RuntimeError("PersonaPromptLoader not initialized. Call init_persona_loader() first.")
    
    return _loader.get_persona_prompt(persona_id_requested)


def list_available_personas() -> list[str]:
    """List all available persona IDs."""
    if _loader is None:
        return []
    return _loader.list_available_personas()


def list_all_metadata() -> list[PersonaMetadata]:
    """Get metadata for all available personas."""
    if _loader is None:
        return []
    return _loader.list_all_metadata()


def get_default_persona_id() -> str:
    """Get the default persona ID."""
    return DEFAULT_PERSONA_ID
