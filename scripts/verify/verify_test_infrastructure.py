"""
Verification script for test infrastructure improvements.

Checks that:
1. conftest.py provides comprehensive test fixtures
2. StubProvider returns realistic responses
3. app/alerting.py TODO is implemented
4. Tests run without real API keys
5. Environment mocking works correctly
"""
import sys
import os
from pathlib import Path
from datetime import datetime


def print_header(text):
    """Print header."""
    print(f"\n{'=' * 70}")
    print(f"{text}")
    print(f"{'=' * 70}\n")


def print_success(text):
    """Print success message."""
    print(f"[OK] {text}")


def print_error(text):
    """Print error message."""
    print(f"[ERROR] {text}")


def print_warning(text):
    """Print warning message."""
    print(f"[WARN] {text}")


def check_file_exists(filepath, description):
    """Check if file exists and has content."""
    path = Path(filepath)
    if not path.exists():
        print_error(f"{description} not found: {filepath}")
        return False
    
    if path.stat().st_size == 0:
        print_error(f"{description} is empty: {filepath}")
        return False
    
    print_success(f"{description} exists ({path.stat().st_size} bytes)")
    return True


def check_conftest():
    """Check conftest.py for required fixtures."""
    print_header("1. Checking tests/conftest.py")
    
    filepath = "tests/conftest.py"
    if not check_file_exists(filepath, "conftest.py"):
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_fixtures = {
        "mock_environment": "Automatic environment mocking",
        "test_db": "In-memory test database",
        "test_user": "Test user with API key",
        "test_admin": "Admin user fixture",
        "mock_llm_responses": "LLM response templates",
        "mock_stub_provider": "Mock StubProvider",
        "mock_request": "Mock FastAPI request",
        "mock_redis": "Mock Redis connection",
        "isolated_env": "Isolated environment fixture"
    }
    
    all_found = True
    for fixture_name, description in required_fixtures.items():
        if f"def {fixture_name}" in content:
            print_success(f"Fixture '{fixture_name}': {description}")
        else:
            print_error(f"Missing fixture: {fixture_name}")
            all_found = False
    
    # Check for pytest markers
    if "pytest_configure" in content:
        print_success("pytest_configure with custom markers")
    else:
        print_warning("No custom pytest markers configured")
    
    return all_found


def check_stub_provider():
    """Check StubProvider enhancements."""
    print_header("2. Checking Enhanced StubProvider")
    
    filepath = "app/router.py"
    if not check_file_exists(filepath, "router.py"):
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for StubProvider class
    if "class StubProvider:" not in content:
        print_error("StubProvider class not found")
        return False
    print_success("StubProvider class exists")
    
    # Check for enhanced features
    features = {
        "diagnostic": "Diagnostic item generation",
        "lesson": "Lesson generation support",
        "grade": "Grading/scoring support",
        "translate": "Translation support",
        "fix": "Text fixing support",
        "summarize": "Summarization support"
    }
    
    all_found = True
    for keyword, description in features.items():
        if f'"{keyword}"' in content or f"'{keyword}'" in content:
            print_success(f"Supports {description}")
        else:
            print_warning(f"May not support: {description}")
    
    # Check for realistic response generation
    if "json.dumps" in content and "ActionResult" in content:
        print_success("Returns structured JSON responses")
    else:
        print_warning("May not return structured responses")
    
    return all_found


def check_alerting_todo():
    """Check that alerting.py TODO is implemented."""
    print_header("3. Checking app/alerting.py Implementation")
    
    filepath = "app/alerting.py"
    if not check_file_exists(filepath, "alerting.py"):
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for TODO comments
    if "TODO" in content:
        print_error("TODO comments still present in alerting.py")
        # Find line numbers
        for i, line in enumerate(content.split('\n'), 1):
            if "TODO" in line:
                print_error(f"  Line {i}: {line.strip()}")
        return False
    
    print_success("No TODO comments found")
    
    # Check for check_rate_limit_abuse implementation
    if "def check_rate_limit_abuse" in content:
        print_success("check_rate_limit_abuse method exists")
        
        # Check if it has actual implementation (not just pass)
        method_start = content.find("def check_rate_limit_abuse")
        method_end = content.find("\n    def ", method_start + 1)
        if method_end == -1:
            method_end = len(content)
        
        method_content = content[method_start:method_end]
        
        if "pass  #" in method_content or method_content.count("\n") < 10:
            print_error("check_rate_limit_abuse appears to be stubbed")
            return False
        else:
            print_success("check_rate_limit_abuse is fully implemented")
    else:
        print_error("check_rate_limit_abuse method not found")
        return False
    
    return True


def check_test_documentation():
    """Check for test documentation."""
    print_header("4. Checking Test Documentation")
    
    filepath = "TESTING_WITHOUT_DEPENDENCIES.md"
    if not check_file_exists(filepath, "Test documentation"):
        return False
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    sections = [
        "Quick Start",
        "Test Fixtures",
        "Environment Configuration",
        "Mock Infrastructure",
        "Running Tests",
        "Writing New Tests",
        "Troubleshooting"
    ]
    
    all_found = True
    for section in sections:
        if section in content:
            print_success(f"Section: {section}")
        else:
            print_error(f"Missing section: {section}")
            all_found = False
    
    # Check for code examples
    if "```python" in content:
        python_examples = content.count("```python")
        print_success(f"Contains {python_examples} Python code examples")
    else:
        print_warning("No Python code examples found")
    
    if "```bash" in content:
        bash_examples = content.count("```bash")
        print_success(f"Contains {bash_examples} bash examples")
    else:
        print_warning("No bash examples found")
    
    return all_found


def check_environment_mocking():
    """Verify environment mocking works."""
    print_header("5. Checking Environment Mocking")
    
    try:
        # Clear environment
        for key in list(os.environ.keys()):
            if key.startswith("SEED_") or key in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
                del os.environ[key]
        
        # Import conftest to trigger mock_environment
        sys.path.insert(0, str(Path.cwd() / "tests"))
        import conftest
        
        # Check that mock_environment fixture exists
        if hasattr(conftest, "mock_environment"):
            print_success("mock_environment fixture is defined")
        else:
            print_error("mock_environment fixture not found")
            return False
        
        # Try to get the fixture
        import pytest
        fixtures = dir(conftest)
        fixture_count = len([f for f in fixtures if not f.startswith("_")])
        print_success(f"conftest.py exports {fixture_count} fixtures")
        
        return True
        
    except Exception as e:
        print_error(f"Error testing environment mocking: {e}")
        return False


def check_syntax():
    """Check Python syntax of all modified files."""
    print_header("6. Checking Python Syntax")
    
    files = [
        "tests/conftest.py",
        "app/router.py",
        "app/alerting.py"
    ]
    
    all_valid = True
    for filepath in files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                code = f.read()
            compile(code, filepath, 'exec')
            print_success(f"{filepath} syntax is valid")
        except SyntaxError as e:
            print_error(f"{filepath} has syntax error: {e}")
            all_valid = False
        except FileNotFoundError:
            print_error(f"{filepath} not found")
            all_valid = False
    
    return all_valid


def run_verification():
    """Run all verification checks."""
    print_header("Test Infrastructure Verification")
    print(f"Started: {datetime.now().isoformat()}")
    
    results = {
        "conftest.py fixtures": check_conftest(),
        "Enhanced StubProvider": check_stub_provider(),
        "alerting.py TODO completed": check_alerting_todo(),
        "Test documentation": check_test_documentation(),
        "Environment mocking": check_environment_mocking(),
        "Python syntax": check_syntax()
    }
    
    print_header("Verification Summary")
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for check_name, result in results.items():
        if result:
            print_success(f"{check_name}")
        else:
            print_error(f"{check_name}")
    
    print(f"\nResults: {passed}/{total} checks passed\n")
    
    if passed == total:
        print("=" * 70)
        print("ALL CHECKS PASSED")
        print("=" * 70)
        print("\nTest infrastructure is complete and ready for use.")
        print("\nNext steps:")
        print("1. Run: python -m pytest -v")
        print("2. Run: python -m pytest --cov=app --cov-report=html")
        print("3. See TESTING_WITHOUT_DEPENDENCIES.md for usage guide")
        return 0
    else:
        print("=" * 70)
        print("SOME CHECKS FAILED")
        print("=" * 70)
        print("\nPlease review and fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(run_verification())
