"""
Backward compatibility helpers for Client Contract V1.

Handles normalization of old request formats to maintain compatibility
during the transition period (recommended: 1 week).
"""

import logging


# Language name to code mapping
LANGUAGE_NAME_TO_CODE = {
    # Common full names to ISO 639-1 codes
    "english": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "arabic": "ar",
    "hindi": "hi",
    "dutch": "nl",
    "polish": "pl",
    "turkish": "tr",
    "swedish": "sv",
    "norwegian": "no",
    "danish": "da",
    "finnish": "fi",
    "greek": "el",
    "hebrew": "he",
    "thai": "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "malay": "ms",
}

# Old level format to CEFR mapping
LEVEL_NAME_TO_CEFR = {
    "beginner": "A1",
    "elementary": "A2",
    "intermediate": "B1",
    "upper-intermediate": "B2",
    "upperintermediate": "B2",
    "upper_intermediate": "B2",
    "advanced": "C1",
    "proficient": "C2",
}


def normalize_language_code(lang: str) -> str:
    """
    Normalize language input to ISO 639-1 code.
    
    Accepts both language names (e.g., "English") and codes (e.g., "en").
    Returns lowercase 2-letter code if recognized, otherwise returns original input.
    
    Args:
        lang: Language name or code
        
    Returns:
        Normalized language code
    """
    if not lang:
        return lang
    
    lang_lower = lang.lower().strip()
    
    # Check if it's already a valid 2-letter code
    if len(lang_lower) == 2:
        return lang_lower
    
    # Try to map from name
    if lang_lower in LANGUAGE_NAME_TO_CODE:
        normalized = LANGUAGE_NAME_TO_CODE[lang_lower]
        logging.info(
            "[COMPAT] Normalized language name to code",
            extra={"original": lang, "normalized": normalized}
        )
        return normalized
    
    # Return as-is (validation will catch invalid codes downstream)
    return lang


def normalize_level_guess(level: str) -> str:
    """
    Normalize level input to CEFR band.
    
    Accepts both old level names (e.g., "beginner", "intermediate")
    and CEFR codes (e.g., "A1", "B1").
    
    Args:
        level: Level name or CEFR code
        
    Returns:
        Normalized CEFR code
    """
    if not level:
        return "A2"  # Default
    
    level_upper = level.upper().strip()
    level_lower = level.lower().strip()
    
    # Check if it's already a valid CEFR code
    if level_upper in ["A1", "A2", "B1", "B2", "C1", "C2"]:
        return level_upper
    
    # Try to map from old level name
    if level_lower in LEVEL_NAME_TO_CEFR:
        normalized = LEVEL_NAME_TO_CEFR[level_lower]
        logging.info(
            "[COMPAT] Normalized level name to CEFR",
            extra={"original": level, "normalized": normalized}
        )
        return normalized
    
    # Return default if unrecognized
    logging.warning(
        "[COMPAT] Unrecognized level format, using default",
        extra={"original": level, "default": "A2"}
    )
    return "A2"
