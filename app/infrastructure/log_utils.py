"""
Logging utilities with PII masking and security best practices.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


def mask_api_key(api_key: str) -> str:
    """
    Mask API key for safe logging.
    
    Shows only last 4 characters for identification.
    
    Args:
        api_key: Full API key
        
    Returns:
        Masked string like "****xyz1" or "***" for short keys
    """
    if not api_key:
        return "***"
    if len(api_key) <= 4:
        return "***"
    return "****" + api_key[-4:]


def mask_email(email: str) -> str:
    """
    Mask email address for safe logging.
    
    Shows first 2 chars of username and full domain.
    Example: "user@example.com" -> "us***@example.com"
    
    Args:
        email: Email address
        
    Returns:
        Masked email or original if not valid email format
    """
    if not email or '@' not in email:
        return email
    
    parts = email.split('@')
    if len(parts) != 2:
        return email
    
    username, domain = parts
    if len(username) <= 2:
        masked_username = "*" * len(username)
    else:
        masked_username = username[:2] + "***"
    
    return f"{masked_username}@{domain}"


def mask_pii(text: str) -> str:
    """
    Mask potential PII in text for safe logging.
    
    Detects and masks:
    - Email addresses
    - Credit card numbers (basic pattern)
    - API keys (seed_* pattern)
    
    Args:
        text: Text potentially containing PII
        
    Returns:
        Text with PII masked
    """
    # Mask email addresses
    text = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        lambda m: mask_email(m.group(0)),
        text
    )
    
    # Mask credit card patterns (basic, any 13-16 digit sequence)
    text = re.sub(
        r'\b\d{13,16}\b',
        '[CARD_REDACTED]',
        text
    )
    
    # Mask API keys with seed_ prefix
    text = re.sub(
        r'\bseed_[A-Za-z0-9_-]{20,}\b',
        lambda m: mask_api_key(m.group(0)),
        text
    )
    
    return text


def sanitize_log_extra(extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sanitize extra fields for structured logging.
    
    Masks known sensitive fields and applies PII detection.
    
    Args:
        extra: Dictionary of extra fields for logging
        
    Returns:
        Sanitized dictionary safe for logging
    """
    if not extra:
        return {}
    
    sanitized = {}
    sensitive_fields = {
        'api_key', 'apiKey', 'password', 'token', 
        'secret', 'authorization', 'x-api-key'
    }
    
    for key, value in extra.items():
        # Mask known sensitive fields
        if key.lower() in sensitive_fields:
            if isinstance(value, str):
                sanitized[key] = mask_api_key(value)
            else:
                sanitized[key] = "***"
        # Mask email-like fields
        elif 'email' in key.lower() and isinstance(value, str):
            sanitized[key] = mask_email(value)
        # Apply PII detection to string values
        elif isinstance(value, str):
            sanitized[key] = mask_pii(value)
        else:
            sanitized[key] = value
    
    return sanitized


def safe_log_user_input(user_input: str, max_length: int = 500) -> str:
    """
    Prepare user input for safe logging.
    
    Truncates long inputs and masks PII.
    
    Args:
        user_input: User-provided text
        max_length: Maximum length to log
        
    Returns:
        Safe string for logging
    """
    masked = mask_pii(user_input)
    
    if len(masked) <= max_length:
        return masked
    
    return masked[:max_length] + f"... (truncated, {len(masked)} total chars)"


# ---------------------------------------------------------------------------
# Logging filter — attach to any handler to auto-mask PII in `extra` fields
# and in the formatted message.
# ---------------------------------------------------------------------------


class PIIMaskingFilter:
    """``logging.Filter`` that masks PII in log records.

    Attaching this filter to a handler (or the root logger) causes:
    * ``record.__dict__`` keys that look like PII to be masked via
      :func:`sanitize_log_extra`.
    * The ``record.msg`` string (after %-formatting) to be scanned via
      :func:`mask_pii`.

    Usage::

        import logging
        from app.infrastructure.log_utils import PIIMaskingFilter

        logging.getLogger().addFilter(PIIMaskingFilter())
    """

    # Keys that are standard logging attributes and should never be touched.
    _LOGGING_INTERNALS = frozenset({
        "name", "msg", "args", "created", "relativeCreated", "exc_info",
        "exc_text", "stack_info", "lineno", "funcName", "pathname",
        "filename", "module", "thread", "threadName", "process",
        "processName", "levelname", "levelno", "msecs", "message",
        "taskName",
    })

    def filter(self, record) -> bool:  # noqa: A003  (stdlib name)
        # 1. Mask extra fields added by callers.
        for key in list(record.__dict__):
            if key.startswith("_") or key in self._LOGGING_INTERNALS:
                continue
            val = record.__dict__[key]
            if isinstance(val, str):
                record.__dict__[key] = mask_pii(val)

        # 2. Mask PII that may be interpolated into the message template.
        try:
            if isinstance(record.msg, str):
                record.msg = mask_pii(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: mask_pii(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        mask_pii(a) if isinstance(a, str) else a for a in record.args
                    )
        except Exception:
            pass  # never break logging

        return True
