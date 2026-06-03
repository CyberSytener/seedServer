# Testing Without External Dependencies

**Complete guide to running tests locally without API keys or external services**

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Test Fixtures](#test-fixtures)
4. [Environment Configuration](#environment-configuration)
5. [Mock Infrastructure](#mock-infrastructure)
6. [Running Tests](#running-tests)
7. [Writing New Tests](#writing-new-tests)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The SEED server test suite is designed to run **completely offline** without requiring:

- Real API keys (OpenAI, Gemini)
- External services (Redis optional for most tests)
- Production `.env` configuration
- Network connectivity

All tests use the **StubProvider** for LLM operations and **mock fixtures** for external dependencies.

---

## Quick Start

### Prerequisites

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Or just pytest essentials
pip install pytest pytest-asyncio pytest-cov pytest-mock
```

### Run All Tests

**Important**: Always run tests from the project root directory:

```bash
# From project root (seed_server/)
pytest -v

# Or explicitly
python -m pytest -v

# With coverage report
pytest --cov=app --cov-report=html

# Run only unit tests (skip integration tests)
pytest -m unit -v

# Run fast tests only (skip slow tests)
pytest -m "not slow" -v
```

**Note**: Tests use `pytest.ini` configuration which automatically:
- Sets the Python path correctly (no sys.path hacks needed)
- Discovers tests in the `tests/` directory
- Applies default options for consistent behavior

### Expected Results

All tests should pass without any `.env` file or API keys:

```
================================ test session starts =================================
tests/test_api.py::test_create_user_and_limits PASSED                          [ 20%]
tests/test_auth_flows.py::test_bearer_token_auth_valid_key PASSED              [ 40%]
tests/test_llm_validator.py::test_sanitize_json_response PASSED                [ 60%]
...
================================ 25 passed in 2.34s ==================================
```

---

## Test Fixtures

### Automatic Environment Mocking

The `tests/conftest.py` file provides automatic fixtures that run for all tests:

```python
@pytest.fixture(scope="session", autouse=True)
def mock_environment():
    """
    Automatically mocks all environment variables.
    No .env file needed!
    """
    # Sets SEED_DEFAULT_PROVIDER_FAST=stub
    # Sets SEED_DEFAULT_PROVIDER_BATCH=stub
    # Sets empty API keys: OPENAI_API_KEY=""
    # etc.
```

This fixture:
- ✅ Runs automatically for ALL tests
- ✅ Prevents accidental API key usage
- ✅ Ensures consistent test environment
- ✅ No configuration needed

### Database Fixtures

```python
def test_with_database(test_db):
    """test_db provides clean in-memory SQLite database"""
    test_db.execute("SELECT * FROM users")
    # Database is automatically cleaned up after test

def test_with_user(test_user):
    """test_user creates user with API key"""
    user_id, api_key = test_user
    # Use authenticated user in test

def test_with_admin(test_admin):
    """test_admin creates admin user"""
    admin_id, admin_api_key = test_admin
    # Use admin user in test
```

### LLM Mock Fixtures

```python
def test_llm_operation(mock_llm_responses):
    """Realistic LLM response templates"""
    diagnostic_response = mock_llm_responses["diagnostic_item"]
    # Returns properly formatted JSON response

def test_with_stub_provider(mock_stub_provider):
    """Mock StubProvider with realistic responses"""
    result = await mock_stub_provider.run(
        model="stub",
        instructions="Generate diagnostic item",
        input_text='{"skill": "grammar"}'
    )
    # Returns ActionResult with realistic data
```

### Request Mocking

```python
def test_auth(mock_request):
    """Create mock FastAPI request"""
    request = mock_request(
        headers={"Authorization": "Bearer test_key"},
        path="/api/test"
    )
    # Test authentication logic
```

---

## Environment Configuration

### No .env File Required

Tests use **automatic environment mocking**:

```python
# conftest.py sets these automatically:
os.environ["SEED_DEFAULT_PROVIDER_FAST"] = "stub"
os.environ["SEED_DEFAULT_PROVIDER_BATCH"] = "stub"
os.environ["OPENAI_API_KEY"] = ""  # Empty - prevents accidental usage
os.environ["GEMINI_API_KEY"] = ""  # Empty - prevents accidental usage
```

### Per-Test Environment Overrides

If a specific test needs custom environment:

```python
def test_custom_config(monkeypatch):
    """Override environment for this test only"""
    monkeypatch.setenv("SEED_PROMPT_TEST_MODE", "true")
    monkeypatch.setenv("SEED_PARSER_VERSION", "optimized")
    
    # Test with custom configuration
    from app.settings import get_settings
    settings = get_settings()
    assert settings.prompt_test_mode == True
```

### Isolated Test Environment

Use the `isolated_env` fixture for complete isolation:

```python
def test_isolated(isolated_env, test_db_path):
    """Test runs in completely isolated environment"""
    # Has own database, stub providers, no shared state
```

---

## Mock Infrastructure

### StubProvider: Realistic LLM Mocking

The enhanced `StubProvider` in `app/router.py` provides realistic responses:

```python
class StubProvider:
    """
    Returns realistic mock LLM responses based on operation type.
    
    Supports:
    - Diagnostic item generation (JSON formatted)
    - Lesson generation (structured tasks)
    - Grading/scoring (feedback and scores)
    - Translation (with confidence)
    - Text fixing (cleanup)
    - Summarization (truncation)
    """
```

#### Example: Diagnostic Item Generation

```python
# Input
instructions = "Generate a diagnostic item for grammar"
input_text = '{"skill": "grammar", "difficulty": 2.0}'

# StubProvider returns:
{
    "item": {
        "id": "stub_item_0042",
        "skill": "grammar",
        "difficulty": 2.0,
        "question": "The cat ___ on the mat.",
        "options": ["sits", "sit", "sitting", "sat"],
        "correctAnswer": "sits",
        "explanation": "For third-person singular subjects..."
    }
}
```

#### Example: Grading

```python
# Input
instructions = "Grade this submission"
input_text = "goes"  # Student answer

# StubProvider returns:
{
    "score": 0.85,
    "isCorrect": true,
    "feedback": "Good work!",
    "corrections": [],
    "explanation": "Your answer demonstrates understanding..."
}
```

### Redis Mocking

```python
def test_with_redis(mock_redis):
    """In-memory Redis mock"""
    mock_redis.set("test_key", "test_value")
    assert mock_redis.get("test_key") == "test_value"
    # No actual Redis connection needed
```

---

## Running Tests

### Unit Tests Only (Fast)

```bash
# Run tests marked as unit tests
pytest -m unit -v

# Typical output:
# 18 passed in 0.42s
```

### Integration Tests (Requires Redis)

```bash
# Run integration tests (may skip if Redis unavailable)
pytest -m integration -v

# Tests automatically skip if Redis not available:
# "Redis not available for integration tests - SKIPPED"
```

### With Coverage

```bash
# Generate coverage report
pytest --cov=app --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=app --cov-report=html
open htmlcov/index.html  # View in browser
```

### Specific Test Files

```bash
# Run specific test file
pytest tests/test_llm_validator.py -v

# Run specific test
pytest tests/test_llm_validator.py::test_sanitize_json_response -v

# Run tests matching pattern
pytest -k "auth" -v  # Runs all tests with "auth" in name
```

### CI/CD Mode

```bash
# Run as CI would (strict, with coverage)
pytest --cov=app --cov-report=term --cov-fail-under=70 -v

# Exit code 0 = all passed, coverage >= 70%
# Exit code 1 = failures or coverage < 70%
```

---

## Writing New Tests

### Basic Test Structure

```python
"""
Test module description.

All tests here use stub providers and mock fixtures.
No external dependencies required.
"""
import pytest
from app.models import SomeModel


@pytest.mark.unit
def test_something_simple():
    """Test description."""
    result = some_function()
    assert result == expected_value


@pytest.mark.unit
def test_with_fixtures(test_db, test_user):
    """Test with database and user."""
    user_id, api_key = test_user
    
    # Test logic here
    result = do_something(test_db, user_id)
    
    assert result is not None
```

### Testing LLM Operations

```python
@pytest.mark.unit
def test_diagnostic_generation(test_db, test_user):
    """Test diagnostic item generation using StubProvider."""
    from app.diagnostic_engine import generate_diagnostic_items
    
    user_id, api_key = test_user
    
    # No need to mock - StubProvider is default in tests
    items = generate_diagnostic_items(
        db=test_db,
        user_id=user_id,
        native_lang="English",
        target_lang="French",
        blueprint=[{"skill": "grammar", "difficulty": 2.0}]
    )
    
    # StubProvider returns realistic mock data
    assert len(items) > 0
    assert items[0]["skill"] == "grammar"
```

### Testing Authentication

```python
@pytest.mark.unit
def test_bearer_token_auth(test_db, test_user, mock_request):
    """Test Bearer token authentication."""
    from app.auth import authenticate
    
    user_id, api_key = test_user
    
    request = mock_request(
        headers={"Authorization": f"Bearer {api_key}"}
    )
    
    auth_ctx = authenticate(request, test_db)
    
    assert auth_ctx.user_id == user_id
    assert auth_ctx.is_admin == False
```

### Testing with Custom Environment

```python
@pytest.mark.unit
def test_with_custom_env(monkeypatch):
    """Test with custom environment configuration."""
    monkeypatch.setenv("SEED_PROMPT_TEST_MODE", "true")
    
    from app.settings import get_settings
    settings = get_settings()
    
    assert settings.prompt_test_mode == True
```

### Async Tests

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_operation():
    """Test async function."""
    from app.router import execute_action
    
    result = await execute_action(
        action="fix",
        input_text="hello  world",
        options={},
        mode="fast"
    )
    
    assert result.provider == "stub"
    assert "hello" in result.text
```

---

## Troubleshooting

### Tests Fail: "Missing API Key"

**Symptom**: Tests fail with messages about missing `OPENAI_API_KEY` or `GEMINI_API_KEY`

**Solution**: Ensure `conftest.py` is present and loaded:

```bash
# Verify conftest.py exists
ls tests/conftest.py

# Run with verbose pytest discovery
pytest --collect-only
```

The `mock_environment` fixture should run automatically. If not:

```python
# Add to top of failing test file
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
```

### Tests Use Real API Keys

**Symptom**: Tests make actual API calls, consume credits

**Solution**: 

1. Check that StubProvider is default:
```python
# In tests, verify:
from app.settings import get_settings
settings = get_settings()
assert settings.default_provider_fast == "stub"
```

2. Remove any `.env` file from test directory:
```bash
# Don't have .env in tests/
rm tests/.env
```

3. Explicitly set provider in test:
```python
def test_something(monkeypatch):
    monkeypatch.setenv("SEED_DEFAULT_PROVIDER_FAST", "stub")
    # Rest of test
```

### Redis Tests Fail

**Symptom**: Tests skip with "Redis not available"

**Options**:

1. **Install Redis** (for integration tests):
```bash
# On macOS
brew install redis
brew services start redis

# On Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# On Windows
# Use WSL or Docker: docker run -d -p 6379:6379 redis
```

2. **Skip integration tests**:
```bash
pytest -m "not integration" -v
```

3. **Use mock Redis**:
```python
def test_with_redis(mock_redis):
    """Uses in-memory mock instead of real Redis"""
    mock_redis.set("key", "value")
```

### Import Errors

**Symptom**: `ModuleNotFoundError: No module named 'app'`

**Solution**: Tests automatically add parent directory to path via `conftest.py`. If still failing:

```python
# Add to top of test file
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### Database Locked Errors

**Symptom**: `sqlite3.OperationalError: database is locked`

**Solution**: Use in-memory databases for tests:

```python
def test_something(test_db):
    """test_db fixture uses :memory: database"""
    # No file locking issues
```

### Slow Tests

**Symptom**: Tests take too long

**Solution**:

1. **Skip slow tests**:
```bash
pytest -m "not slow" -v
```

2. **Run in parallel**:
```bash
pip install pytest-xdist
pytest -n auto  # Use all CPU cores
```

3. **Profile tests**:
```bash
pytest --durations=10  # Show 10 slowest tests
```

---

## Best Practices

### ✅ DO

- Use `test_db` fixture for database tests
- Use `test_user` and `test_admin` for auth tests
- Mark tests with `@pytest.mark.unit` or `@pytest.mark.integration`
- Use StubProvider by default (it's automatic!)
- Use `monkeypatch` for environment overrides
- Write tests that don't require `.env` file
- Clean up test data in fixtures (not in tests)

### ❌ DON'T

- Don't use real API keys in tests
- Don't skip fixture cleanup (use `yield` in fixtures)
- Don't share state between tests (use fixtures)
- Don't hardcode paths (use `tmp_path` fixture)
- Don't commit `.env` to tests directory
- Don't make actual HTTP requests (use mocks)

---

## Summary

The SEED server test infrastructure is designed for **complete independence** from external services:

1. **No API keys required** - StubProvider handles all LLM operations
2. **No .env file required** - conftest.py mocks environment automatically  
3. **No Redis required** - Unit tests use mock Redis or skip gracefully
4. **No network required** - All tests run offline

To run tests:

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Run tests
pytest -v

# That's it! All tests should pass without any configuration.
```

**All tests run in CI/CD with zero secrets or external dependencies.**

---

## Additional Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-asyncio for async tests](https://pytest-asyncio.readthedocs.io/)
- [pytest fixtures guide](https://docs.pytest.org/en/stable/fixture.html)
- [Coverage.py documentation](https://coverage.readthedocs.io/)
