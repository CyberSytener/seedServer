"""
Tests for LLM response validator.
"""
import pytest
import json
from pydantic import BaseModel, Field

from app.core.llm.validator import (
    LLMResponseValidator,
    validate_llm_json,
    get_validator,
    ValidationResult
)


class SimpleModel(BaseModel):
    """Simple test model."""
    name: str
    age: int


class ComplexModel(BaseModel):
    """Complex test model with nested fields."""
    id: str
    title: str
    items: list[str]
    metadata: dict[str, str]


def test_validator_initialization():
    """Test validator can be initialized."""
    validator = LLMResponseValidator()
    assert validator is not None


def test_sanitize_removes_markdown():
    """Test markdown code block removal."""
    response = "```json\n{\"name\": \"test\", \"age\": 25}\n```"
    validator = get_validator()
    
    sanitized, warnings = validator.sanitize_json_response(response)
    
    assert "```" not in sanitized
    assert "{\"name\": \"test\", \"age\": 25}" in sanitized
    assert len(warnings) > 0
    assert any("markdown" in w.lower() for w in warnings)


def test_sanitize_removes_preamble():
    """Test removal of text before JSON."""
    response = "Here is the JSON output:\n{\"name\": \"test\", \"age\": 25}"
    validator = get_validator()
    
    sanitized, warnings = validator.sanitize_json_response(response)
    
    assert sanitized.startswith("{")
    assert "Here is" not in sanitized
    assert len(warnings) > 0


def test_sanitize_removes_postamble():
    """Test removal of text after JSON."""
    response = "{\"name\": \"test\", \"age\": 25}\nThat's the output!"
    validator = get_validator()
    
    sanitized, warnings = validator.sanitize_json_response(response)
    
    assert sanitized.endswith("}")
    assert "That's" not in sanitized
    assert len(warnings) > 0


def test_validate_valid_json():
    """Test validation of valid JSON response."""
    response = '{"name": "Alice", "age": 30}'
    
    result = validate_llm_json(response, SimpleModel)
    
    assert result.is_valid
    assert result.success
    assert result.data is not None
    assert result.data.name == "Alice"
    assert result.data.age == 30
    assert result.error is None


def test_validate_json_with_markdown():
    """Test validation handles markdown wrappers."""
    response = '```json\n{"name": "Bob", "age": 25}\n```'
    
    result = validate_llm_json(response, SimpleModel)
    
    assert result.is_valid
    assert result.data.name == "Bob"
    assert len(result.warnings) > 0


def test_validate_invalid_json():
    """Test validation detects invalid JSON."""
    response = '{invalid json syntax'
    
    result = validate_llm_json(response, SimpleModel)
    
    assert not result.is_valid
    assert result.success is False
    assert result.data is None
    assert "JSON decode error" in result.error
    assert result.correction_prompt is not None


def test_validate_missing_required_field():
    """Test validation detects missing required fields."""
    response = '{"name": "Charlie"}'  # Missing 'age'
    
    result = validate_llm_json(response, SimpleModel)
    
    assert not result.is_valid
    assert result.data is None
    assert "validation failed" in result.error.lower()
    assert result.correction_prompt is not None


def test_validate_wrong_type():
    """Test validation detects type mismatches."""
    response = '{"name": "David", "age": "twenty-five"}'  # age should be int
    
    result = validate_llm_json(response, SimpleModel)
    
    assert not result.is_valid
    assert result.data is None
    assert result.correction_prompt is not None


def test_validate_complex_model():
    """Test validation with complex nested model."""
    response = '''
    {
        "id": "test_123",
        "title": "Test Item",
        "items": ["item1", "item2", "item3"],
        "metadata": {"key1": "value1", "key2": "value2"}
    }
    '''
    
    result = validate_llm_json(response, ComplexModel)
    
    assert result.is_valid
    assert result.data.id == "test_123"
    assert len(result.data.items) == 3
    assert result.data.metadata["key1"] == "value1"


def test_sanitize_removes_invisible_characters():
    """Test removal of invisible Unicode characters."""
    response = '\u200b{"name": "test", "age": 25}\ufeff'
    validator = get_validator()
    
    sanitized, warnings = validator.sanitize_json_response(response)
    
    assert '\u200b' not in sanitized
    assert '\ufeff' not in sanitized


def test_validation_result_properties():
    """Test ValidationResult properties."""
    response = '{"name": "Eve", "age": 28}'
    result = validate_llm_json(response, SimpleModel)
    
    assert result.is_valid
    assert result.success
    assert hasattr(result, 'data')
    assert hasattr(result, 'error')
    assert hasattr(result, 'warnings')
    assert hasattr(result, 'sanitized_input')
    assert hasattr(result, 'correction_prompt')


def test_correction_prompt_for_json_error():
    """Test correction prompt generation for JSON errors."""
    response = '{"name": "test", "age": }'  # Invalid JSON
    result = validate_llm_json(response, SimpleModel)
    
    assert not result.is_valid
    assert result.correction_prompt is not None
    assert "JSON SYNTAX ERROR" in result.correction_prompt
    assert "valid json" in result.correction_prompt.lower()  # Case insensitive


def test_correction_prompt_for_schema_error():
    """Test correction prompt generation for schema errors."""
    response = '{}'  # Missing required fields
    result = validate_llm_json(response, SimpleModel)
    
    assert not result.is_valid
    assert result.correction_prompt is not None
    assert "SCHEMA VALIDATION" in result.correction_prompt
    assert "SimpleModel" in result.correction_prompt


def test_empty_response():
    """Test handling of empty response."""
    response = ''
    result = validate_llm_json(response, SimpleModel)
    
    assert not result.is_valid
    assert result.error is not None


def test_whitespace_only_response():
    """Test handling of whitespace-only response."""
    response = '   \n\n\t  '
    result = validate_llm_json(response, SimpleModel)
    
    assert not result.is_valid


def test_nested_code_blocks():
    """Test handling of nested markdown blocks."""
    response = '''
    ```json
    ```json
    {"name": "test", "age": 25}
    ```
    ```
    '''
    validator = get_validator()
    
    sanitized, warnings = validator.sanitize_json_response(response)
    
    assert "{" in sanitized
    assert "name" in sanitized


def test_validator_with_context():
    """Test validation with context for logging."""
    response = '{"name": "Frank", "age": 35}'
    context = {"user_id": "user123", "attempt": 1}
    
    result = validate_llm_json(response, SimpleModel, context)
    
    assert result.is_valid
    assert result.data.name == "Frank"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
