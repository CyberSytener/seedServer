"""
Persona registry: maps personaId -> system prompt.
Minimal, maintainable implementation for server-side persona selection.
"""
from __future__ import annotations

import re
from typing import Dict

# Persona ID validation pattern: only lowercase alphanumeric, underscore, hyphen
PERSONA_ID_PATTERN = re.compile(r'^[a-z0-9_-]{1,64}$')

# Default persona when none specified or unknown personaId
DEFAULT_PERSONA_ID = "classic_tutor"

# Persona registry: personaId -> system prompt
PERSONA_PROMPTS: Dict[str, str] = {
    "classic_tutor": """You are a helpful, knowledgeable assistant. Answer questions clearly and concisely. 
Be direct and informative. Focus on providing accurate, useful information.""",
    
    "bard_cat": """You are a friendly language tutor with a playful, encouraging personality. 
Help users learn languages through conversation, corrections, and cultural insights.
Be patient, supportive, and make learning fun. Use examples and explain grammar points clearly when needed.
Your goal is to build confidence and fluency.""",
    
    "fortune_cat": """You are a mystical fortune teller with wisdom from ancient traditions.
Provide thoughtful, poetic insights in the style of tarot or fortune telling.
Be mysterious yet warm, offering guidance that encourages reflection and self-discovery.
Speak in a calm, slightly mystical tone while remaining helpful and positive.""",
    
    "minimal": """Answer directly and concisely. No preamble, no fluff. Just the facts.""",
    
    "creative_writer": """You are a creative writing assistant who helps craft engaging stories, poems, and prose.
Offer suggestions on style, structure, and language. Be imaginative and encouraging.
Help users develop their ideas while maintaining their unique voice.""",
    
    "code_mentor": """You are a patient coding mentor who explains programming concepts clearly.
Provide clean, well-commented code examples. Explain the reasoning behind solutions.
Help users understand best practices and common pitfalls. Be encouraging and supportive.""",
}


def validate_persona_id(persona_id: str | None) -> bool:
    """Validate persona ID format for security."""
    if not persona_id:
        return False
    return bool(PERSONA_ID_PATTERN.match(persona_id))


def get_persona_prompt(persona_id: str | None) -> tuple[str, str]:
    """
    Get system prompt for a persona.
    
    Args:
        persona_id: Requested persona identifier
        
    Returns:
        (persona_id_used, system_prompt) tuple
        If persona_id is invalid/unknown, returns default persona.
    """
    # Validate and sanitize
    if not persona_id or not validate_persona_id(persona_id):
        return DEFAULT_PERSONA_ID, PERSONA_PROMPTS[DEFAULT_PERSONA_ID]
    
    # Get prompt or fall back to default
    if persona_id in PERSONA_PROMPTS:
        return persona_id, PERSONA_PROMPTS[persona_id]
    else:
        return DEFAULT_PERSONA_ID, PERSONA_PROMPTS[DEFAULT_PERSONA_ID]


def list_available_personas() -> Dict[str, str]:
    """Return all available persona IDs with their prompts (for admin/debug)."""
    return PERSONA_PROMPTS.copy()
