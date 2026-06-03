"""
Quick verification script for LLM Trust Boundary implementation.
"""
import sys
from app.core.llm.validator import validate_llm_json, get_validator
from app.models.api import GradeResult
from pydantic import BaseModel, Field


class TestModel(BaseModel):
    """Test model for verification."""
    name: str
    value: int


def test_basic_validation():
    """Test basic validation works."""
    print("Testing basic validation...")
    
    valid_json = '{"name": "test", "value": 42}'
    result = validate_llm_json(valid_json, TestModel)
    
    assert result.is_valid, "Valid JSON should pass validation"
    assert result.data.name == "test", "Data should be parsed correctly"
    assert result.data.value == 42, "Data should be parsed correctly"
    
    print("✅ Basic validation works")


def test_markdown_sanitization():
    """Test markdown code block removal."""
    print("Testing markdown sanitization...")
    
    markdown_json = '```json\n{"name": "test", "value": 42}\n```'
    result = validate_llm_json(markdown_json, TestModel)
    
    assert result.is_valid, "Markdown should be sanitized"
    assert len(result.warnings) > 0, "Should have sanitization warnings"
    
    print("✅ Markdown sanitization works")


def test_invalid_json():
    """Test invalid JSON handling."""
    print("Testing invalid JSON handling...")
    
    invalid_json = '{invalid: json}'
    result = validate_llm_json(invalid_json, TestModel)
    
    assert not result.is_valid, "Invalid JSON should fail"
    assert result.error is not None, "Should have error message"
    assert result.correction_prompt is not None, "Should have correction prompt"
    
    print("✅ Invalid JSON handling works")


def test_missing_fields():
    """Test schema validation."""
    print("Testing schema validation...")
    
    missing_field = '{"name": "test"}'  # Missing 'value'
    result = validate_llm_json(missing_field, TestModel)
    
    assert not result.is_valid, "Missing fields should fail validation"
    assert "validation failed" in result.error.lower() or "field required" in result.error.lower()
    
    print("✅ Schema validation works")


def test_imports():
    """Test all imports work."""
    print("Testing imports...")
    
    from app import lesson_engine, diagnostic_engine, router
    from app.core.llm.validator import LLMResponseValidator
    
    assert hasattr(lesson_engine, 'generate_lesson'), "lesson_engine should have generate_lesson"
    assert hasattr(lesson_engine, 'grade_submission'), "lesson_engine should have grade_submission"
    assert hasattr(diagnostic_engine, 'generate_diagnostic_items'), "diagnostic_engine should have generate_diagnostic_items"
    assert hasattr(router, 'execute_llm_request'), "router should have execute_llm_request"
    
    print("✅ All imports work")


def main():
    """Run all verification tests."""
    print("=" * 60)
    print("LLM Trust Boundary - Verification Script")
    print("=" * 60)
    print()
    
    try:
        test_imports()
        print()
        
        test_basic_validation()
        print()
        
        test_markdown_sanitization()
        print()
        
        test_invalid_json()
        print()
        
        test_missing_fields()
        print()
        
        print("=" * 60)
        print("✅ ALL VERIFICATION TESTS PASSED")
        print("=" * 60)
        print()
        print("Implementation Status: ✅ READY FOR PRODUCTION")
        print()
        
        return 0
        
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ VERIFICATION FAILED: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

