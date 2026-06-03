"""
LLM Output Validation and Trust Boundary Enforcement

This module provides robust schema validation and fail-safe behavior for LLM responses.
It ensures that all LLM outputs are validated before being used in the application.

Security principles:
1. Never trust LLM output directly
2. Always validate against strict schemas
3. Provide meaningful fallbacks
4. Log all validation failures
5. Sanitize output before parsing
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional, TypeVar, Generic
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ValidationError


T = TypeVar('T', bound=BaseModel)


class ValidationStrategy(Enum):
    """Validation strategies for LLM responses."""
    STRICT = "strict"  # Must pass validation or raise
    FALLBACK = "fallback"  # Return fallback on failure
    RETRY_PROMPT = "retry_prompt"  # Build correction prompt for retry


@dataclass
class ValidationResult(Generic[T]):
    """Result of LLM response validation."""
    success: bool
    data: Optional[T]
    error: Optional[str]
    warnings: list[str]
    sanitized_input: str
    correction_prompt: Optional[str] = None
    
    @property
    def is_valid(self) -> bool:
        """Check if validation succeeded."""
        return self.success and self.data is not None


class LLMResponseValidator:
    """
    Validates and sanitizes LLM responses with fail-safe behavior.
    
    This class implements a trust boundary between LLM outputs and application logic.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    def sanitize_json_response(self, response: str) -> tuple[str, list[str]]:
        """
        Sanitize LLM response to extract valid JSON.
        
        Removes:
        - Markdown code blocks (```json, ```)
        - Leading/trailing whitespace
        - Explanatory text before/after JSON
        - Common LLM artifacts
        
        Returns:
            Tuple of (sanitized_json, list_of_warnings)
        """
        warnings = []
        original = response
        cleaned = response.strip()
        
        # Remove markdown code blocks
        if cleaned.startswith("```"):
            warnings.append("Removed markdown code block wrapper")
            lines = cleaned.split("\n")
            
            # Find start and end of code block
            start_idx = 1 if lines[0].startswith("```") else 0
            end_idx = len(lines)
            
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith("```"):
                    end_idx = i
                    break
            
            cleaned = "\n".join(lines[start_idx:end_idx])
            cleaned = cleaned.strip()
        
        # Try to find JSON object/array boundaries
        # Look for outermost { } or [ ]
        json_start = -1
        json_end = -1
        
        # Find first { or [
        for i, char in enumerate(cleaned):
            if char in ('{', '['):
                json_start = i
                break
        
        # Find matching closing bracket
        if json_start >= 0:
            bracket_stack = []
            open_char = cleaned[json_start]
            close_char = '}' if open_char == '{' else ']'
            
            for i in range(json_start, len(cleaned)):
                char = cleaned[i]
                if char in ('{', '['):
                    bracket_stack.append(char)
                elif char in ('}', ']'):
                    if bracket_stack:
                        bracket_stack.pop()
                        if not bracket_stack:
                            json_end = i + 1
                            break
            
            if json_start > 0:
                warnings.append(f"Removed {json_start} characters of preamble")
            
            if json_end > 0:
                cleaned = cleaned[json_start:json_end]
                if json_end < len(original):
                    warnings.append(f"Removed {len(original) - json_end} characters of trailing text")
        
        # Remove zero-width spaces and other invisible characters
        cleaned = re.sub(r'[\u200b-\u200d\ufeff]', '', cleaned)
        
        return cleaned, warnings
    
    def validate_json_structure(
        self,
        response: str,
        model_class: type[T],
        context: Optional[dict[str, Any]] = None
    ) -> ValidationResult[T]:
        """
        Validate LLM response against a Pydantic model schema.
        
        Args:
            response: Raw LLM response text
            model_class: Pydantic model class to validate against
            context: Optional context for error messages and logging
            
        Returns:
            ValidationResult with parsed data or error information
        """
        context = context or {}
        
        # Step 1: Sanitize response
        try:
            sanitized, warnings = self.sanitize_json_response(response)
        except Exception as e:
            return ValidationResult(
                success=False,
                data=None,
                error=f"Sanitization failed: {str(e)}",
                warnings=[],
                sanitized_input=response[:200]
            )
        
        # Step 2: Parse JSON
        try:
            parsed_json = json.loads(sanitized)
        except json.JSONDecodeError as e:
            error_msg = f"JSON decode error at position {e.pos}: {e.msg}"
            
            # Try to provide helpful context
            if e.pos < len(sanitized):
                start = max(0, e.pos - 50)
                end = min(len(sanitized), e.pos + 50)
                context_snippet = sanitized[start:end]
                error_msg += f"\nContext: ...{context_snippet}..."
            
            correction_prompt = self._build_json_correction_prompt(
                sanitized, 
                e, 
                model_class
            )
            
            return ValidationResult(
                success=False,
                data=None,
                error=error_msg,
                warnings=warnings,
                sanitized_input=sanitized[:500],
                correction_prompt=correction_prompt
            )
        
        # Step 3: Validate against Pydantic schema
        try:
            validated_data = model_class.model_validate(parsed_json)
            
            self.logger.debug(
                f"Successfully validated LLM response as {model_class.__name__}",
                extra={"warnings": warnings, "context": context}
            )
            
            return ValidationResult(
                success=True,
                data=validated_data,
                error=None,
                warnings=warnings,
                sanitized_input=sanitized
            )
            
        except ValidationError as e:
            error_msg = self._format_validation_errors(e)
            correction_prompt = self._build_schema_correction_prompt(
                parsed_json,
                e,
                model_class
            )
            
            return ValidationResult(
                success=False,
                data=None,
                error=f"Schema validation failed: {error_msg}",
                warnings=warnings,
                sanitized_input=sanitized[:500],
                correction_prompt=correction_prompt
            )
    
    def validate_with_retry(
        self,
        response: str,
        model_class: type[T],
        retry_callback: Optional[Callable[[str], str]] = None,
        max_retries: int = 2,
        context: Optional[dict[str, Any]] = None
    ) -> ValidationResult[T]:
        """
        Validate with automatic retry using correction prompts.
        
        Args:
            response: Initial LLM response
            model_class: Pydantic model to validate against
            retry_callback: Function that takes correction prompt and returns new LLM response
            max_retries: Maximum number of retry attempts
            context: Optional context for logging
            
        Returns:
            Final validation result (success or failure after retries)
        """
        current_response = response
        
        for attempt in range(max_retries + 1):
            result = self.validate_json_structure(current_response, model_class, context)
            
            if result.is_valid:
                if attempt > 0:
                    self.logger.info(
                        f"Validation succeeded after {attempt} retries",
                        extra={"model": model_class.__name__, "context": context}
                    )
                return result
            
            # If we have retries left and a callback
            if attempt < max_retries and retry_callback and result.correction_prompt:
                self.logger.warning(
                    f"Validation attempt {attempt + 1} failed, retrying",
                    extra={"error": result.error, "model": model_class.__name__}
                )
                
                try:
                    current_response = retry_callback(result.correction_prompt)
                except Exception as e:
                    self.logger.error(f"Retry callback failed: {e}")
                    break
            else:
                break
        
        # All retries exhausted
        self.logger.error(
            f"Validation failed after {max_retries + 1} attempts",
            extra={
                "model": model_class.__name__,
                "final_error": result.error,
                "context": context
            }
        )
        
        return result
    
    def _format_validation_errors(self, error: ValidationError) -> str:
        """Format Pydantic validation errors into readable message."""
        errors = []
        for err in error.errors():
            loc = ".".join(str(x) for x in err['loc'])
            msg = err['msg']
            errors.append(f"{loc}: {msg}")
        
        return "; ".join(errors[:5])  # Limit to first 5 errors
    
    def _build_json_correction_prompt(
        self,
        invalid_json: str,
        parse_error: json.JSONDecodeError,
        model_class: type[T]
    ) -> str:
        """Build correction prompt for JSON syntax errors."""
        return f"""PREVIOUS OUTPUT HAD JSON SYNTAX ERROR:
Error: {parse_error.msg} at position {parse_error.pos}

You MUST return valid JSON matching the {model_class.__name__} schema.

Requirements:
- Valid JSON syntax (proper quotes, commas, brackets)
- No trailing commas
- All strings properly quoted
- All required fields present

Start with {{ and end with }}. No markdown code blocks. No explanatory text."""
    
    def _build_schema_correction_prompt(
        self,
        invalid_data: dict,
        validation_error: ValidationError,
        model_class: type[T]
    ) -> str:
        """Build correction prompt for schema validation errors."""
        error_summary = self._format_validation_errors(validation_error)
        
        # Try to extract schema info
        schema_info = ""
        try:
            schema = model_class.model_json_schema()
            required_fields = schema.get('required', [])
            if required_fields:
                schema_info = f"\n\nRequired fields: {', '.join(required_fields)}"
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        return f"""PREVIOUS OUTPUT FAILED SCHEMA VALIDATION:
{error_summary}{schema_info}

You MUST return valid JSON that exactly matches the {model_class.__name__} schema.

Fix these specific issues:
{error_summary}

Return ONLY valid JSON. No markdown. No extra text."""


# Global validator instance
_validator: Optional[LLMResponseValidator] = None


def get_validator() -> LLMResponseValidator:
    """Get or create global validator instance."""
    global _validator
    if _validator is None:
        _validator = LLMResponseValidator()
    return _validator


def validate_llm_json(
    response: str,
    model_class: type[T],
    context: Optional[dict[str, Any]] = None
) -> ValidationResult[T]:
    """
    Convenience function to validate LLM JSON response.
    
    Usage:
        result = validate_llm_json(llm_response, Lesson)
        if result.is_valid:
            lesson = result.data
        else:
            handle_error(result.error)
    """
    validator = get_validator()
    return validator.validate_json_structure(response, model_class, context)
